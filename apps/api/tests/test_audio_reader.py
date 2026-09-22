"""O leitor de fala: qual é, como fala com o whisper, e o que ele recusa.

Mesma forma do leitor de fotos: o app só sabe que há "um transcritor, num
endereço configurável", e o endereço só pode ser da própria máquina ou da
rede interna — nenhuma gravação sai da fazenda, por construção.
"""

from __future__ import annotations

import io
import json
import math
import shutil
import struct
import wave

import pytest

from app.audio.decoding import to_wav_16k_mono
from app.audio.speech_reader import SpokenEventReader, build_audio_reader
from app.audio.transcriber import (
    FAKE_SPEECH,
    FakeAudioTranscriber,
    TranscriberFormatError,
    WhisperCppTranscriber,
)
from app.core.config import Settings


def _settings(**kwargs) -> Settings:
    return Settings(_env_file=None, **kwargs)


_PRODUCAO = dict(
    environment="production",
    runtime_role="worker",
    reader_provider="ollama",
    reader_url="http://host.docker.internal:11434",
    postgres_url="postgresql+asyncpg://u:p@db/x",
    redis_url="redis://redis:6379/0",
    minio_url="http://minio:9000",
    minio_access_key="k",
    minio_secret_key="s",
)


class TestWhichReader:
    def test_the_fake_is_the_default(self) -> None:
        """Sem configurar nada, ninguém transcreve de verdade por engano."""
        leitor = build_audio_reader(_settings())

        assert isinstance(leitor, SpokenEventReader)
        assert isinstance(leitor.transcriber, FakeAudioTranscriber)

    def test_whisper_uses_the_configured_address(self) -> None:
        leitor = build_audio_reader(
            _settings(audio_provider="whisper", audio_url="http://host.docker.internal:8081")
        )

        assert isinstance(leitor.transcriber, WhisperCppTranscriber)
        assert leitor.transcriber.url == "http://host.docker.internal:8081"

    def test_an_external_address_is_refused_when_building(self) -> None:
        """A guarda vale na construção: nenhuma gravação chega a sair."""
        with pytest.raises(ValueError):
            build_audio_reader(
                _settings(audio_provider="whisper", audio_url="https://transcreve.exemplo.com")
            )

    def test_whisper_without_an_address_says_what_is_missing(self) -> None:
        with pytest.raises(RuntimeError, match="AUDIO_URL"):
            build_audio_reader(_settings(audio_provider="whisper", audio_url=""))


class TestProductionSettings:
    def test_the_fake_transcriber_is_refused_in_production(self) -> None:
        """O falso devolve sempre a mesma frase: em produção viraria produção
        inventada esperando aprovação, com a gravação de verdade ignorada."""
        with pytest.raises(ValueError, match="audio_provider"):
            Settings(_env_file=None, audio_provider="fake", **_PRODUCAO)

    def test_whisper_in_production_needs_the_address(self) -> None:
        with pytest.raises(ValueError, match="audio_url"):
            Settings(_env_file=None, audio_provider="whisper", audio_url="", **_PRODUCAO)

    def test_a_complete_production_worker_starts(self) -> None:
        Settings(
            _env_file=None,
            audio_provider="whisper",
            audio_url="http://host.docker.internal:8081",
            **_PRODUCAO,
        )


class _Servidor:
    """Faz o papel do whisper-server: devolve as respostas na ordem."""

    def __init__(self, *respostas: bytes) -> None:
        self.respostas = list(respostas)
        self.chamadas: list[tuple[str, dict[str, str], bytes]] = []

    def __call__(self, url: str, campos: dict[str, str], wav: bytes, prazo: float) -> bytes:
        self.chamadas.append((url, campos, wav))
        return self.respostas[min(len(self.chamadas), len(self.respostas)) - 1]


def _detalhada(*trechos: tuple[float, float, str], duracao: float) -> bytes:
    """A resposta do whisper-server com marcas de tempo. Como no de verdade,
    cada trecho começa com espaço — a não ser o que continua a palavra do
    anterior, marcado aqui com "+"."""
    textos = [t[1:] if t.startswith("+") else (t if t.startswith(" ") else " " + t) for _, _, t in trechos]
    return json.dumps({
        "text": "".join(textos),
        "duration": duracao,
        "segments": [{"start": a, "end": b, "text": t} for (a, b, _), t in zip(trechos, textos)],
    }).encode()


def _fala(segundos: float, silencio: tuple[float, float] | None = None, taxa: int = 16_000) -> bytes:
    """WAV 16 kHz mono com "voz" (um tom), e silêncio onde pedido."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as arquivo:
        arquivo.setnchannels(1)
        arquivo.setsampwidth(2)
        arquivo.setframerate(taxa)
        amostras = []
        for n in range(int(segundos * taxa)):
            t = n / taxa
            calado = silencio is not None and silencio[0] <= t < silencio[1]
            amostras.append(0 if calado else int(6_000 * math.sin(2 * math.pi * 220 * t)))
        arquivo.writeframes(struct.pack(f"<{len(amostras)}h", *amostras))
    return buffer.getvalue()


def _segundos(wav: bytes) -> float:
    with wave.open(io.BytesIO(wav)) as arquivo:
        return arquivo.getnframes() / arquivo.getframerate()


class TestTalkingToWhisper:
    def test_the_request_asks_for_portuguese_and_temperature_zero(self) -> None:
        """Temperatura zero: a mesma gravação dá a mesma transcrição, e é isso
        que permite comparar duas versões do tradutor."""
        servidor = _Servidor(_detalhada((0.0, 3.0, "A 497 deu 18."), duracao=3.0))
        transcritor = WhisperCppTranscriber(url="http://127.0.0.1:8081", model="m", post=servidor)

        texto = transcritor.transcribe(b"RIFF...")

        assert texto == "A 497 deu 18."
        [(url, campos, wav)] = servidor.chamadas
        assert url == "http://127.0.0.1:8081/inference"
        assert campos["language"] == "pt"
        assert campos["temperature"] == "0"
        assert wav == b"RIFF..."

    def test_a_skipped_stretch_of_speech_is_heard_again_on_its_own(self) -> None:
        """Medido numa gravação do titular, feita pelo gravador do navegador:
        o whisper transcreveu "Mensagem de teste" (0 a 1,6 s) e SALTOU para
        29,98 s — sumiram duas vacas, sem erro nenhum. É o salto de marca de
        tempo. Perguntar de novo sem marcas não resolveu nessa gravação; o
        trecho pulado, ouvido sozinho, saiu perfeito. O buraco entre trechos
        é o sinal (numa gravação boa, o maior foi de 0,44 s)."""
        servidor = _Servidor(
            _detalhada((0.0, 1.6, "Mensagem de teste."), (29.98, 32.2, "Produziu 7 litros."), duracao=34.0),
            _detalhada((0.0, 4.2, "Vaca 417 Pandora"), (4.2, 26.0, "Produziu 5 litros"), duracao=28.38),
        )
        transcritor = WhisperCppTranscriber(url="http://127.0.0.1:8081", model="m", post=servidor)

        texto = transcritor.transcribe(_fala(34.0))

        assert texto.split("\n") == [
            "Mensagem de teste.",
            "Vaca 417 Pandora",
            "Produziu 5 litros",
            "Produziu 7 litros.",
        ]
        [_, (_, campos, fatia)] = servidor.chamadas
        assert campos["response_format"] == "verbose_json"  # com marcas: erra menos dígito
        assert _segundos(fatia) == pytest.approx(29.98 - 1.6, abs=0.01)

    def test_speech_lost_at_the_end_is_heard_again_too(self) -> None:
        servidor = _Servidor(
            _detalhada((0.0, 9.0, "Vaca 417."), duracao=40.0),
            _detalhada((1.0, 12.0, "Vaca 633."), (12.0, 28.0, "Vaca 419."), duracao=31.0),
        )
        transcritor = WhisperCppTranscriber(url="http://127.0.0.1:8081", model="m", post=servidor)

        assert transcritor.transcribe(_fala(40.0)).split("\n") == ["Vaca 417.", "Vaca 633.", "Vaca 419."]

    def test_a_recovered_stretch_with_its_own_hole_is_heard_again_up_to_a_limit(self) -> None:
        servidor = _Servidor(
            _detalhada((0.0, 1.0, "Vaca 417."), (30.0, 31.0, "Vaca 419."), duracao=31.0),
            _detalhada((0.0, 2.0, "Produziu 8 litros."), duracao=29.0),
            _detalhada((0.0, 2.0, "Vaca 633."), duracao=27.0),
        )
        transcritor = WhisperCppTranscriber(url="http://127.0.0.1:8081", model="m", post=servidor)

        texto = transcritor.transcribe(_fala(31.0))

        assert texto.split("\n") == ["Vaca 417.", "Produziu 8 litros.", "Vaca 633.", "Vaca 419."]
        # A gravação, o buraco, e o buraco que sobrou dele — e para aí.
        assert len(servidor.chamadas) == 3

    def test_a_real_pause_is_not_asked_again(self) -> None:
        """Pausa longa de verdade é silêncio, e whisper sobre silêncio inventa
        frase de legenda de vídeo. Sem som no buraco, não se pergunta nada."""
        servidor = _Servidor(
            _detalhada((0.0, 3.0, "Vaca 417, 8 litros."), (20.0, 23.0, "Vaca 633, 4 litros."), duracao=24.0)
        )
        transcritor = WhisperCppTranscriber(url="http://127.0.0.1:8081", model="m", post=servidor)

        texto = transcritor.transcribe(_fala(24.0, silencio=(3.0, 20.0)))

        assert texto.split("\n") == ["Vaca 417, 8 litros.", "Vaca 633, 4 litros."]
        assert len(servidor.chamadas) == 1

    def test_a_phrase_invented_in_the_stretch_is_dropped(self) -> None:
        servidor = _Servidor(
            _detalhada((0.0, 3.0, "Vaca 417, 8 litros."), (20.0, 23.0, "Vaca 633, 4 litros."), duracao=24.0),
            _detalhada((0.0, 5.0, " Legendas pela comunidade Amara.org"), duracao=17.0),
        )
        transcritor = WhisperCppTranscriber(url="http://127.0.0.1:8081", model="m", post=servidor)

        assert transcritor.transcribe(_fala(24.0)).split("\n") == [
            "Vaca 417, 8 litros.",
            "Vaca 633, 4 litros.",
        ]

    def test_each_segment_is_a_line(self) -> None:
        """A pausa entre trechos é fronteira para o tradutor."""
        servidor = _Servidor(
            _detalhada((0.0, 5.0, " 7 pela manhã, mais 5 da tarde"), (5.2, 9.0, " Pequina produziu 6,5 litros"), duracao=9.5)
        )
        transcritor = WhisperCppTranscriber(url="http://127.0.0.1:8081", model="m", post=servidor)

        assert transcritor.transcribe(b"RIFF...") == (
            "7 pela manhã, mais 5 da tarde\nPequina produziu 6,5 litros"
        )

    def test_a_word_split_between_segments_is_glued_back(self) -> None:
        """Medido: o whisper partiu "litros" entre dois trechos ("...8 lit" e
        "ros no total"), e a quebra de linha entre trechos separava a
        palavra — sobrava "lit; ros" como observação. O trecho que continua a
        palavra começa sem espaço; o que começa palavra nova, com espaço."""
        servidor = _Servidor(
            _detalhada(
                (0.0, 5.0, " Produziu 5 litros pela manhã, totalizando 8 lit"),
                (5.0, 5.6, "+ros no total"),
                (5.6, 9.0, " A vaca 633, gigante"),
                duracao=9.5,
            )
        )
        transcritor = WhisperCppTranscriber(url="http://127.0.0.1:8081", model="m", post=servidor)

        assert transcritor.transcribe(b"RIFF...").split("\n") == [
            "Produziu 5 litros pela manhã, totalizando 8 litros no total",
            "A vaca 633, gigante",
        ]

    def test_a_continuous_transcript_is_asked_only_once(self) -> None:
        servidor = _Servidor(
            _detalhada((0.0, 5.0, "Vaca 417."), (5.4, 11.0, "Vaca 633."), duracao=11.5)
        )
        transcritor = WhisperCppTranscriber(url="http://127.0.0.1:8081", model="m", post=servidor)

        transcritor.transcribe(b"RIFF...")

        assert len(servidor.chamadas) == 1

    @pytest.mark.parametrize("resposta", [b"<html>erro</html>", b'{"sem": "texto"}'])
    def test_an_answer_that_is_not_a_transcript_is_refused(self, resposta) -> None:
        transcritor = WhisperCppTranscriber(
            url="http://127.0.0.1:8081", model="m", post=_Servidor(resposta)
        )

        with pytest.raises(TranscriberFormatError):
            transcritor.transcribe(b"RIFF...")


class _Transcritor:
    def __init__(self, texto: str) -> None:
        self.texto = texto
        self.ouviu: list[bytes] = []

    def transcribe(self, wav: bytes) -> str:
        self.ouviu.append(wav)
        return self.texto


class TestTheSpeechReader:
    def _leitor(self, texto: str) -> tuple[SpokenEventReader, _Transcritor]:
        transcritor = _Transcritor(texto)
        leitor = SpokenEventReader(
            transcritor, decode=lambda conteudo: b"wav:" + conteudo, model_name="modelo"
        )
        return leitor, transcritor

    def test_the_recording_is_converted_then_transcribed_then_translated(self) -> None:
        leitor, transcritor = self._leitor(FAKE_SPEECH)

        extraction = leitor.extract(b"m4a", kind="audio")

        assert transcritor.ouviu == [b"wav:m4a"]
        [producao] = extraction.events
        assert (producao.event_type, producao.brinco) == ("production", "497")
        assert producao.fields == {"producao": "33", "parcelas": "18 + 15"}

    def test_the_date_is_left_for_whoever_knows_when_it_was_sent(self) -> None:
        """A fala não tem cabeçalho: a data é o dia do envio, e quem sabe
        disso é quem lê a gravação guardada."""
        leitor, _ = self._leitor(FAKE_SPEECH)

        assert leitor.extract(b"m4a", kind="audio").reference_date is None

    def test_the_version_says_model_and_grammar(self) -> None:
        leitor, _ = self._leitor(FAKE_SPEECH)

        assert leitor.extract(b"m4a", kind="audio").extractor_version.startswith("modelo/fala-")

    def test_a_recording_of_silence_creates_nothing(self) -> None:
        """Whisper sobre silêncio inventa frase de legenda de vídeo."""
        leitor, _ = self._leitor(" Legendas pela comunidade Amara.org")

        with pytest.raises(TranscriberFormatError):
            leitor.extract(b"m4a", kind="audio")

    def test_a_photo_is_not_for_this_reader(self) -> None:
        leitor, _ = self._leitor(FAKE_SPEECH)

        with pytest.raises(ValueError):
            leitor.extract(b"jpg", kind="photo")


def _wav(segundos: float = 1.0, taxa: int = 44_100, canais: int = 2) -> bytes:
    """Um tom de 440 Hz em estéreo 44,1 kHz: o formato que o whisper NÃO quer."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as arquivo:
        arquivo.setnchannels(canais)
        arquivo.setsampwidth(2)
        arquivo.setframerate(taxa)
        amostras = (int(8_000 * math.sin(2 * math.pi * 440 * n / taxa)) for n in range(int(taxa * segundos)))
        arquivo.writeframes(b"".join(struct.pack("<h", a) * canais for a in amostras))
    return buffer.getvalue()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg só existe no contêiner do worker")
class TestTheConversion:
    def test_any_recording_becomes_16k_mono(self) -> None:
        convertido = to_wav_16k_mono(_wav(), max_seconds=300)

        with wave.open(io.BytesIO(convertido)) as arquivo:
            assert (arquivo.getframerate(), arquivo.getnchannels()) == (16_000, 1)

    def test_a_long_recording_is_cut_at_the_limit(self) -> None:
        convertido = to_wav_16k_mono(_wav(segundos=3.0), max_seconds=1)

        with wave.open(io.BytesIO(convertido)) as arquivo:
            assert arquivo.getnframes() / arquivo.getframerate() == pytest.approx(1.0, abs=0.05)

    def test_something_that_is_not_audio_is_refused(self) -> None:
        with pytest.raises(TranscriberFormatError):
            to_wav_16k_mono(b"isto nao e audio nenhum", max_seconds=300)
