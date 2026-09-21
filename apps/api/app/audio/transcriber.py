"""O transcritor: gravação de voz em WAV → texto.

O app não sabe que existe whisper: sabe que há "um transcritor, num endereço
configurável" (`AUDIO_URL`), como já sabe do leitor de fotos. Trocar a
máquina onde o modelo roda é mudar uma variável, não mexer em código.

O endereço só pode ser da própria máquina ou da rede interna
(`ensure_local_url`): nenhuma gravação sai da fazenda, por construção.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from typing import Protocol

from app.core.local_url import ensure_local_url


class TranscriberUnavailable(RuntimeError):
    """O transcritor local não respondeu (desligado, sem modelo)."""


class TranscriberTimeout(TranscriberUnavailable):
    """A transcrição passou do tempo."""


class TranscriberFormatError(ValueError):
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
        corpo = self._post(
            f"{self.url}/inference",
            {"language": self.language, "temperature": "0", "response_format": "json"},
            wav,
            self.timeout,
        )
        try:
            resposta = json.loads(corpo)
        except (ValueError, UnicodeDecodeError) as error:
            raise TranscriberFormatError("O transcritor respondeu algo que não é JSON.") from error
        texto = resposta.get("text") if isinstance(resposta, dict) else None
        if not isinstance(texto, str):
            raise TranscriberFormatError("A resposta do transcritor não traz o texto.")
        return texto
