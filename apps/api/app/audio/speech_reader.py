"""O leitor de fala: gravação → transcrição → eventos.

Implementa o mesmo contrato do leitor de fotos (`EventExtractor`), e é isso
que deixa o worker tratar as duas mídias pelo mesmo caminho. Três passos, e
só o do meio usa modelo:

1. converter a gravação em WAV 16 kHz mono (ffmpeg);
2. transcrever (whisper, na infraestrutura da fazenda);
3. traduzir a fala em linhas e as linhas em eventos — código nosso, o mesmo
   tradutor que a folha de pesagem usa.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache, partial

from app.audio.decoding import to_wav_16k_mono
from app.audio.speech_to_lines import AUDIO_ORIGIN, is_phantom, speech_to_lines
from app.audio.transcriber import (
    AudioTranscriber,
    FakeAudioTranscriber,
    TranscriberFormatError,
    WhisperCppTranscriber,
)
from app.core.config import Settings, get_settings
from app.services.event_extraction import EventExtraction, EventExtractor
from app.services.reading_to_events import lines_to_events

EXTRACTOR_NAME = "leitor-local-fala"
#: Muda quando as regras do tradutor da fala mudam: a nota é por versão.
GRAMMAR_VERSION = "fala-v3"


class SpokenEventReader:
    def __init__(
        self,
        transcriber: AudioTranscriber,
        *,
        decode: Callable[[bytes], bytes],
        model_name: str,
    ) -> None:
        self.transcriber = transcriber
        self.decode = decode
        self.model_name = model_name

    @property
    def version(self) -> str:
        return f"{self.model_name}/{GRAMMAR_VERSION}"

    def extract(self, content: bytes, *, kind: str) -> EventExtraction:
        if kind != "audio":
            raise ValueError(f"O leitor de fala ouve gravações, não {kind!r}.")
        texto = self.transcriber.transcribe(self.decode(content))
        # Whisper sobre silêncio inventa frase de legenda de vídeo. Se a
        # gravação inteira for só isso, não houve fala — e proposta nenhuma
        # deve nascer dela.
        if is_phantom(texto):
            raise TranscriberFormatError("A gravação não tem fala que se reconheça.")
        # A data fica em branco: a fala não tem cabeçalho, e quem lê a
        # gravação preenche com o dia do envio.
        return lines_to_events(
            speech_to_lines(texto),
            extractor_name=EXTRACTOR_NAME,
            extractor_version=self.version,
            origem=AUDIO_ORIGIN,
        )


def build_audio_reader(settings: Settings) -> EventExtractor:
    """O leitor de fala configurado.

    No falso, a gravação nem é convertida: o CI não tem GPU, e o E2E exercita
    a gramática inteira com a frase fixa — o ffmpeg e o whisper ficam cobertos
    pelos testes unitários e pela medição com gravação real.
    """
    if settings.audio_provider == "fake":
        return SpokenEventReader(
            FakeAudioTranscriber(), decode=lambda content: content, model_name="transcritor-falso"
        )
    if not settings.audio_url:
        raise RuntimeError("AUDIO_URL é obrigatório quando AUDIO_PROVIDER=whisper.")
    transcriber = WhisperCppTranscriber(
        url=settings.audio_url, model=settings.audio_model, language=settings.audio_language
    )
    return SpokenEventReader(
        transcriber,
        decode=partial(to_wav_16k_mono, max_seconds=settings.audio_max_seconds),
        model_name=settings.audio_model,
    )


@lru_cache
def get_audio_reader() -> EventExtractor:
    return build_audio_reader(get_settings())
