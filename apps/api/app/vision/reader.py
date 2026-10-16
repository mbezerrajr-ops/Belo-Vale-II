"""Qual leitor de eventos o worker usa.

O app não sabe que existe Ollama: sabe que há um leitor, num endereço
configurável (`READER_URL`). Por isso tirar o modelo da máquina de hoje e
pô-lo num servidor com GPU — ligado por rede privada — é trocar uma variável
de ambiente, e não mexer em código.

O falso é o padrão: ele deixa o caminho inteiro (foto → worker → proposta)
ser exercitado sem GPU e sem modelo, no CI e em demonstração. Em produção é
recusado pela configuração, porque inventa leitura.
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import Settings, get_settings
from app.services.event_extraction import EventExtractor, FakeEventExtractor
from app.core.gemini import GeminiClient
from app.vision.sheet_reader import GeminiSheetReader, OllamaSheetReader


def build_event_reader(settings: Settings) -> EventExtractor:
    """O leitor descrito pela configuração. Endereço externo é recusado aqui,
    antes de qualquer foto sair (ver `ensure_local_url`)."""
    if settings.reader_provider == "fake":
        return FakeEventExtractor()
    if settings.reader_provider == "gemini":
        key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else ""
        return GeminiSheetReader(client=GeminiClient(api_key=key, model=settings.reader_model))
    if not settings.reader_url:
        raise RuntimeError("READER_URL é obrigatório quando READER_PROVIDER=ollama.")
    return OllamaSheetReader(url=settings.reader_url, model=settings.reader_model)


@lru_cache
def get_event_reader() -> EventExtractor:
    return build_event_reader(get_settings())
