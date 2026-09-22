"""O transcritor: gravação de voz em WAV → texto.

O app não sabe que existe whisper: sabe que há "um transcritor, num endereço
configurável" (`AUDIO_URL`), como já sabe do leitor de fotos. Trocar a
máquina onde o modelo roda é mudar uma variável, não mexer em código.

O endereço só pode ser da própria máquina ou da rede interna
(`ensure_local_url`): nenhuma gravação sai da fazenda, por construção.
"""

from __future__ import annotations

import array
import io
import json
import logging
import math
import socket
import sys
import urllib.error
import urllib.request
import uuid
import wave
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from app.audio.speech_to_lines import is_phantom
from app.core.local_url import ensure_local_url
from app.services.event_extraction import ReaderUnavailableError, UnreadableContentError

logger = logging.getLogger(__name__)

#: Buraco entre trechos transcritos a partir do qual a fala foi PULADA. Numa
#: gravação boa do titular o maior buraco foi de 0,44 s; na que falhou, 28 s.
SKIP_GAP_SECONDS = 8.0
#: Abaixo disto o buraco é pausa de verdade, e não se pergunta nada: whisper
#: sobre silêncio inventa frase. Medido: fala a -18 dBFS, pausa a -44 dBFS
#: (gravação do celular) ou -57 dBFS (gravador do navegador).
SILENCE_DBFS = -40.0
#: Quantas vezes um trecho recuperado ainda pode ter o próprio buraco ouvido
#: de novo.
MAX_RECOVERY_DEPTH = 2


class TranscriberUnavailable(ReaderUnavailableError):
    """O transcritor local não respondeu (desligado, sem modelo)."""


class TranscriberTimeout(TranscriberUnavailable):
    """A transcrição passou do tempo."""


class TranscriberFormatError(UnreadableContentError):
    """O transcritor respondeu algo que não é transcrição, ou a gravação não
    tem fala que se possa transcrever."""


class AudioTranscriber(Protocol):
    def transcribe(self, wav: bytes) -> str: ...


#: A frase que o transcritor falso sempre "ouve". É a mesma que o titular
#: usou para descrever a fala do curral, e casa com o animal que o E2E
#: cadastra (497 PONTA CURTA).
FAKE_SPEECH = "A 497 deu 18 litros de manhã e 15 à tarde."


class FakeAudioTranscriber:
    """Não ouve nada: devolve sempre a mesma frase. Serve ao CI, que não tem
    GPU nem modelo, e à demonstração. Em produção o worker se recusa a subir
    com ele."""

    name = "transcritor-falso"

    def transcribe(self, wav: bytes) -> str:  # noqa: ARG002 - não ouve nada
        return FAKE_SPEECH


#: POST (url, campos, arquivo, prazo) → corpo da resposta.
Post = Callable[[str, dict[str, str], bytes, float], bytes]


def _default_post(url: str, fields: dict[str, str], wav: bytes, timeout: float) -> bytes:
    """Multipart à mão, com a biblioteca padrão: nenhuma dependência nova."""
    limite = uuid.uuid4().hex
    partes = [
        f"--{limite}\r\nContent-Disposition: form-data; name=\"{nome}\"\r\n\r\n{valor}\r\n".encode()
        for nome, valor in fields.items()
    ]
    partes.append(
        f"--{limite}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"fala.wav\"\r\n"
        "Content-Type: audio/wav\r\n\r\n".encode()
        + wav
        + b"\r\n"
    )
    partes.append(f"--{limite}--\r\n".encode())
    request = urllib.request.Request(
        url,
        data=b"".join(partes),
        headers={"Content-Type": f"multipart/form-data; boundary={limite}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except (socket.timeout, TimeoutError) as error:
        raise TranscriberTimeout(f"O transcritor passou do tempo em {url}: {error}") from error
    except urllib.error.URLError as error:
        if isinstance(error.reason, (socket.timeout, TimeoutError)):
            raise TranscriberTimeout(f"O transcritor passou do tempo em {url}") from error
        raise TranscriberUnavailable(f"O transcritor não respondeu em {url}: {error}") from error


class WhisperCppTranscriber:
    """Fala com o `whisper-server` do whisper.cpp: `POST /inference`.

    Temperatura zero: a mesma gravação dá a mesma transcrição, e é isso que
    permite comparar duas versões do tradutor contra o mesmo gabarito.
    """

    def __init__(
        self,
        *,
        url: str,
        model: str,
        language: str = "pt",
        timeout: float = 180.0,
        post: Post | None = None,
    ) -> None:
        self.url = ensure_local_url(url)
        self.model = model
        self.language = language
        self.timeout = timeout
        self._post = post or _default_post

    @property
    def name(self) -> str:
        return self.model

    def transcribe(self, wav: bytes) -> str:
        """A gravação transcrita, um trecho por linha — sem trecho pulado.

        Medido com as gravações do titular: o whisper transcreveu "Mensagem de
        teste" (0 a 1,6 s) e SALTOU para 29,98 s, levando duas ou três vacas
        junto, sem erro nenhum. É o salto de marca de tempo: o modelo prevê o
        fim da janela antes da hora. Aconteceu com ruído leve somado e, sem
        ruído nenhum, com a mesma gravação passada pelo gravador do navegador.

        As marcas de tempo servem de detector: buraco grande entre trechos
        quer dizer fala pulada. E o remédio medido é ouvir de novo SÓ o
        trecho pulado: sozinho, ele saiu perfeito. Perguntar a gravação
        inteira de novo sem marcas foi o primeiro remédio, e não bastou — na
        gravação do navegador ela pulou igual, e sem marcas o modelo ainda
        erra mais dígito ("462" virou "4162"). Brinco errado aparece na caixa
        de Revisão; vaca pulada não aparece em lugar nenhum.
        """
        resposta = self._ask(wav, {"response_format": "verbose_json"})
        trechos = _segments(resposta, offset=0.0)
        if not trechos:
            return _text(resposta)
        buracos = _gaps(trechos, 0.0, _duration(resposta))
        if buracos:
            logger.warning(
                "transcrição pulou %d trecho(s) de fala; ouvindo de novo só esses trechos",
                len(buracos),
            )
            trechos = sorted(
                trechos + self._recover(wav, buracos, depth=1), key=lambda trecho: trecho.start
            )
        return _lines(trechos)

    def _recover(
        self, wav: bytes, buracos: list[tuple[float, float]], *, depth: int
    ) -> list[_Segment]:
        """Cada trecho pulado, ouvido sozinho — a não ser que seja silêncio."""
        recuperados: list[_Segment] = []
        for de, ate in buracos:
            fatia = _slice(wav, de, ate)
            if fatia is None or _level_dbfs(fatia) < SILENCE_DBFS:
                continue  # pausa de verdade: nada a recuperar
            resposta = self._ask(fatia, {"response_format": "verbose_json"})
            novos = [t for t in _segments(resposta, offset=de) if not is_phantom(t.text)]
            recuperados += novos
            if novos and depth < MAX_RECOVERY_DEPTH:
                recuperados += self._recover(wav, _gaps(novos, de, ate), depth=depth + 1)
        return recuperados

    def _ask(self, wav: bytes, extra: dict[str, str]) -> dict:
        corpo = self._post(
            f"{self.url}/inference",
            {"language": self.language, "temperature": "0", **extra},
            wav,
            self.timeout,
        )
        try:
            resposta = json.loads(corpo)
        except (ValueError, UnicodeDecodeError) as error:
            raise TranscriberFormatError("O transcritor respondeu algo que não é JSON.") from error
        if not isinstance(resposta, dict):
            raise TranscriberFormatError("A resposta do transcritor não traz o texto.")
        return resposta


def _text(resposta: dict) -> str:
    texto = resposta.get("text")
    if not isinstance(texto, str):
        raise TranscriberFormatError("A resposta do transcritor não traz o texto.")
    return texto.strip()


@dataclass(frozen=True)
class _Segment:
    start: float
    end: float
    text: str
    #: O trecho continua a palavra do anterior: o whisper partiu "litros" em
    #: "...8 lit" e "ros no total". Trecho que começa palavra nova começa com
    #: espaço; este, não.
    glued: bool = False


def _lines(trechos: list[_Segment]) -> str:
    """Um trecho por linha — menos a palavra partida, que volta a ser uma."""
    linhas: list[str] = []
    for trecho in trechos:
        if trecho.glued and linhas and linhas[-1][-1:].isalpha():
            linhas[-1] += trecho.text
        else:
            linhas.append(trecho.text)
    return "\n".join(linhas)


def _segments(resposta: dict, *, offset: float) -> list[_Segment]:
    """Os trechos, na hora da gravação inteira. Cada trecho é uma pausa
    natural da fala, e vira uma linha: o tradutor usa a quebra de linha como
    fronteira — é por ela que acha "Pequina produziu" no começo de frase. O
    texto corrido às vezes perde o ponto entre uma vaca e outra."""
    trechos: list[_Segment] = []
    for bruto in resposta.get("segments") or []:
        if not isinstance(bruto, dict):
            continue
        cru = str(bruto.get("text", ""))
        texto = cru.strip()
        try:
            inicio, fim = float(bruto["start"]), float(bruto["end"])
        except (KeyError, TypeError, ValueError):
            inicio = fim = trechos[-1].end - offset if trechos else 0.0
        if texto:
            colado = bool(trechos) and not cru[:1].isspace() and cru[:1].isalpha()
            trechos.append(_Segment(offset + inicio, offset + fim, texto, glued=colado))
    return trechos


def _duration(resposta: dict) -> float:
    try:
        return float(resposta.get("duration") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _gaps(trechos: list[_Segment], inicio: float, fim: float) -> list[tuple[float, float]]:
    """Os buracos grandes: antes do primeiro trecho, entre trechos e depois do
    último (quando se sabe onde a gravação acaba)."""
    buracos: list[tuple[float, float]] = []
    anterior = inicio
    for trecho in sorted(trechos, key=lambda t: t.start):
        if trecho.start - anterior > SKIP_GAP_SECONDS:
            buracos.append((anterior, trecho.start))
        anterior = max(anterior, trecho.end)
    if fim and fim - anterior > SKIP_GAP_SECONDS:
        buracos.append((anterior, fim))
    return buracos


def _slice(wav: bytes, de: float, ate: float) -> bytes | None:
    """O pedaço da gravação entre `de` e `ate` segundos, em WAV."""
    try:
        with wave.open(io.BytesIO(wav)) as entrada:
            taxa = entrada.getframerate()
            parametros = entrada.getparams()
            entrada.setpos(min(int(de * taxa), entrada.getnframes()))
            quadros = entrada.readframes(max(0, int((ate - de) * taxa)))
    except (wave.Error, EOFError, ValueError):
        return None
    if not quadros:
        return None
    saida = io.BytesIO()
    with wave.open(saida, "wb") as arquivo:
        arquivo.setparams(parametros)
        arquivo.writeframes(quadros)
    return saida.getvalue()


def _level_dbfs(wav: bytes) -> float:
    """O volume médio do trecho, em dBFS (0 é o máximo)."""
    with wave.open(io.BytesIO(wav)) as arquivo:
        if arquivo.getsampwidth() != 2:
            return 0.0  # formato inesperado: melhor ouvir do que descartar
        amostras = array.array("h")
        amostras.frombytes(arquivo.readframes(arquivo.getnframes()))
    if sys.byteorder == "big":
        amostras.byteswap()
    if not amostras:
        return -math.inf
    rms = math.sqrt(sum(a * a for a in amostras) / len(amostras))
    return 20 * math.log10(rms / 32768) if rms else -math.inf
