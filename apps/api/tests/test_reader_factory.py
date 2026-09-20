"""Qual leitor o worker usa, e como ele é escolhido.

O app não sabe que existe Ollama: sabe que há "um leitor, num endereço
configurável". Trocar a máquina onde o modelo roda é mudar uma variável de
ambiente, não mexer em código — é o que permite tirar o modelo da máquina do
titular sem refazer nada.

O leitor falso é o padrão: é ele que deixa o CI exercitar o caminho inteiro
(foto → worker → proposta) sem GPU e sem modelo.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.services.event_extraction import FakeEventExtractor
from app.vision.reader import build_event_reader
from app.vision.sheet_reader import OllamaSheetReader


def _settings(**kwargs) -> Settings:
    return Settings(_env_file=None, **kwargs)


class TestBuildEventReader:
    def test_the_fake_reader_is_the_default(self) -> None:
        """Sem configurar nada, ninguém lê foto de verdade por engano."""
        reader = build_event_reader(_settings())

        assert isinstance(reader, FakeEventExtractor)

    def test_ollama_uses_the_configured_address_and_model(self) -> None:
        reader = build_event_reader(
            _settings(
                reader_provider="ollama",
                reader_url="http://10.1.2.3:11434",
                reader_model="qwen2.5vl:7b",
            )
        )

        assert isinstance(reader, OllamaSheetReader)
        assert reader.url == "http://10.1.2.3:11434"
        assert reader.model == "qwen2.5vl:7b"

    def test_an_external_address_is_refused_when_building(self) -> None:
        """A guarda vale na construção: nenhuma foto chega a sair."""
        with pytest.raises(ValueError):
            build_event_reader(
                _settings(reader_provider="ollama", reader_url="https://ia.exemplo.com")
            )

    def test_ollama_without_an_address_says_what_is_missing(self) -> None:
        with pytest.raises(RuntimeError, match="READER_URL"):
            build_event_reader(_settings(reader_provider="ollama", reader_url=""))


class TestProductionSettings:
    def test_the_worker_reading_with_ollama_needs_the_address(self) -> None:
        with pytest.raises(ValueError, match="reader_url"):
            Settings(
                _env_file=None,
                environment="production",
                runtime_role="worker",
                reader_provider="ollama",
                reader_url="",
                postgres_url="postgresql+asyncpg://u:p@db/x",
                redis_url="redis://redis:6379/0",
                minio_url="http://minio:9000",
                minio_access_key="k",
                minio_secret_key="s",
            )

    def test_the_fake_reader_is_refused_in_production(self) -> None:
        """O leitor falso inventa leitura: em produção viraria dado inventado
        esperando aprovação, com a foto de verdade ignorada."""
        with pytest.raises(ValueError, match="reader_provider"):
            Settings(
                _env_file=None,
                environment="production",
                runtime_role="worker",
                reader_provider="fake",
                postgres_url="postgresql+asyncpg://u:p@db/x",
                redis_url="redis://redis:6379/0",
                minio_url="http://minio:9000",
                minio_access_key="k",
                minio_secret_key="s",
            )
