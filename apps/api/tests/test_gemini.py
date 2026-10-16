"""A leitura pela API Gemini: o único caminho de foto e gravação para fora.

Decisão do titular (16/10/2026): sem o PC com placa de vídeo, fotos e
gravações são lidas pela API Gemini, na conta paga da fazenda. O destino é
fixo — o endereço do Google, sem configuração — e a chave vem do servidor.
Nenhum teste aqui chama a API: as respostas são montadas no formato dela.
"""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest

from app.audio.speech_reader import build_audio_reader
from app.audio.transcriber import GeminiTranscriber, TranscriberFormatError, sem_horas
from app.core.config import Settings
from app.core.gemini import ENDPOINT, GeminiClient, GeminiFormatError
from app.vision.reader import build_event_reader
from app.vision.sheet_reader import GeminiSheetReader, ReaderFormatError


def _settings(**kwargs: Any) -> Settings:
    return Settings(_env_file=None, **kwargs)


def _reply(text: str, finish: str = "STOP") -> dict[str, Any]:
    return {
        "candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": finish}],
        "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 20},
    }


class Recorder:
    """Faz o papel da API: guarda o que foi enviado e devolve a resposta dada."""

    def __init__(self, reply: dict[str, Any]) -> None:
        self.reply = reply
        self.calls: list[tuple[str, dict[str, Any], dict[str, str], float]] = []

    def __call__(
        self, url: str, body: dict[str, Any], headers: dict[str, str], timeout: float
    ) -> dict[str, Any]:
        self.calls.append((url, body, headers, timeout))
        return self.reply


class TestGeminiClient:
    def test_the_destination_is_fixed_and_the_key_goes_in_the_header(self) -> None:
        post = Recorder(_reply("ok"))
        client = GeminiClient(api_key="chave-de-teste", model="gemini-3.5-flash-lite", post=post)

        client.generate(prompt="Leia.", media=b"\xff\xd8foto", mime_type="image/jpeg")

        url, body, headers, _ = post.calls[0]
        assert url == ENDPOINT.format(model="gemini-3.5-flash-lite")
        assert url.startswith("https://generativelanguage.googleapis.com/")
        assert headers == {"x-goog-api-key": "chave-de-teste"}
        # A chave nunca vai no endereço nem no corpo.
        assert "chave-de-teste" not in url
        assert "chave-de-teste" not in json.dumps(body)
        foto = body["contents"][0]["parts"][0]["inline_data"]
        assert foto["mime_type"] == "image/jpeg"
        assert base64.b64decode(foto["data"]) == b"\xff\xd8foto"
        assert body["generationConfig"]["temperature"] == 0

    def test_a_schema_asks_for_json_in_that_shape(self) -> None:
        post = Recorder(_reply("{}"))
        client = GeminiClient(api_key="k", model="m", post=post)
        schema = {"type": "object", "properties": {"lote": {"type": ["string", "null"]}}}

        client.generate(prompt="Leia.", schema=schema)

        config = post.calls[0][1]["generationConfig"]
        assert config["responseMimeType"] == "application/json"
        assert config["responseJsonSchema"] == schema

    def test_without_a_key_it_refuses_to_start(self) -> None:
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
            GeminiClient(api_key="", model="m")

    @pytest.mark.parametrize("finish", ["MAX_TOKENS", "SAFETY", "RECITATION"])
    def test_a_cut_or_blocked_answer_is_not_a_reading(self, finish: str) -> None:
        client = GeminiClient(api_key="k", model="m", post=Recorder(_reply('{"linhas": [', finish)))
        with pytest.raises(GeminiFormatError, match=finish):
            client.generate(prompt="Leia.")

    def test_no_candidate_is_not_a_reading(self) -> None:
        reply = {"promptFeedback": {"blockReason": "OTHER"}}
        client = GeminiClient(api_key="k", model="m", post=Recorder(reply))
        with pytest.raises(GeminiFormatError, match="OTHER"):
            client.generate(prompt="Leia.")

    def test_the_tokens_are_added_up_to_measure_the_cost(self) -> None:
        client = GeminiClient(api_key="k", model="m", post=Recorder(_reply("ok")))
        client.generate(prompt="a")
        client.generate(prompt="b")
        assert client.total_tokens == {"entrada": 200, "saida": 40, "chamadas": 2}


class TestGeminiSheetReader:
    def test_it_reads_the_json_the_model_answered(self) -> None:
        post = Recorder(_reply('{"formato": "impresso"}'))
        reader = GeminiSheetReader(client=GeminiClient(api_key="k", model="m", post=post))

        assert reader.classify_page(b"\xff\xd8foto") == "impresso"
        assert reader.version.startswith("m/")

    def test_broken_json_is_a_format_error(self) -> None:
        post = Recorder(_reply('{"formato": '))
        reader = GeminiSheetReader(client=GeminiClient(api_key="k", model="m", post=post))
        with pytest.raises(ReaderFormatError):
            reader._chat(prompt="p", schema={}, image=b"x")


class TestGeminiTranscriber:
    def test_it_sends_the_wav_and_returns_the_text(self) -> None:
        post = Recorder(_reply("Vaca 417 Pandora deu 8 litros."))
        transcriber = GeminiTranscriber(client=GeminiClient(api_key="k", model="m", post=post))

        assert transcriber.transcribe(b"RIFFwav") == "Vaca 417 Pandora deu 8 litros."
        audio = post.calls[0][1]["contents"][0]["parts"][0]["inline_data"]
        assert audio["mime_type"] == "audio/wav"

    def test_no_speech_is_not_a_reading(self) -> None:
        transcriber = GeminiTranscriber(
            client=GeminiClient(api_key="k", model="m", post=Recorder(_reply("SEM FALA.")))
        )
        with pytest.raises(TranscriberFormatError):
            transcriber.transcribe(b"RIFFwav")

    def test_litres_written_as_hours_are_undone(self) -> None:
        """Gravação 3 do titular: "sete pela manhã" saiu "7:00 pela manhã"."""
        transcriber = GeminiTranscriber(
            client=GeminiClient(
                api_key="k", model="m", post=Recorder(_reply("7:00 pela manhã, mais 5:00 da tarde."))
            )
        )
        assert transcriber.transcribe(b"RIFFwav") == "7 pela manhã, mais 5 da tarde."

    @pytest.mark.parametrize(
        ("texto", "esperado"),
        [
            ("6:30 de manhã", "6,5 de manhã"),
            ("12:00h à tarde", "12 à tarde"),
            ("às 7:15", "às 7:15"),
            ("brinco 389, 12,5 litros", "brinco 389, 12,5 litros"),
        ],
    )
    def test_sem_horas(self, texto: str, esperado: str) -> None:
        assert sem_horas(texto) == esperado


class TestChoosingGemini:
    def test_the_photo_reader_uses_the_configured_model(self) -> None:
        reader = build_event_reader(
            _settings(
                reader_provider="gemini",
                reader_model="gemini-3.5-flash-lite",
                gemini_api_key="k" * 39,
            )
        )
        assert isinstance(reader, GeminiSheetReader)
        assert reader.model == "gemini-3.5-flash-lite"

    def test_the_speech_reader_uses_the_configured_model(self) -> None:
        reader = build_audio_reader(
            _settings(
                audio_provider="gemini",
                audio_model="gemini-3.5-flash-lite",
                gemini_api_key="k" * 39,
            )
        )
        assert isinstance(reader.transcriber, GeminiTranscriber)
        assert reader.version.startswith("gemini-3.5-flash-lite/")

    def test_without_a_key_the_reader_is_not_built(self) -> None:
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
            build_event_reader(_settings(reader_provider="gemini"))

    def test_the_production_worker_needs_the_key(self) -> None:
        with pytest.raises(ValueError, match="gemini_api_key"):
            _settings(
                environment="production",
                runtime_role="worker",
                postgres_url="postgresql+asyncpg://u:p@db/x",
                redis_url="redis://redis:6379/0",
                minio_url="http://minio:9000",
                minio_access_key="a",
                minio_secret_key="b",
                reader_provider="gemini",
                audio_provider="gemini",
            )

    def test_the_production_worker_starts_with_gemini_and_a_key(self) -> None:
        settings = _settings(
            environment="production",
            runtime_role="worker",
            postgres_url="postgresql+asyncpg://u:p@db/x",
            redis_url="redis://redis:6379/0",
            minio_url="http://minio:9000",
            minio_access_key="a",
            minio_secret_key="b",
            reader_provider="gemini",
            audio_provider="gemini",
            gemini_api_key="k" * 39,
        )
        assert settings.gemini_api_key is not None
