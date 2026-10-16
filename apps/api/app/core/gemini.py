"""O único caminho para fora: a API Gemini, do Google.

Decisão do titular (16/10/2026): sem o PC com placa de vídeo, a leitura de
fotos e de gravações passa a ser feita pela API Gemini, na conta paga da
fazenda — nessa conta o Google não usa o que recebe para treinar modelos.

Por isso este módulo não aceita endereço: o destino é fixo, o da API do
Google. Os leitores locais (Ollama, whisper) continuam presos à rede
interna por `ensure_local_url`; o que se abriu foi este endereço, e só ele.
A chave vem da configuração do servidor e nunca do chamador.
"""

from __future__ import annotations

import base64
import json
import socket
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from app.services.event_extraction import ReaderUnavailableError, UnreadableContentError

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiUnavailable(ReaderUnavailableError):
    """A API não respondeu, recusou a chave ou passou do limite: tentar de novo depois."""


class GeminiTimeout(GeminiUnavailable):
    """A resposta não veio no tempo."""


class GeminiFormatError(UnreadableContentError):
    """A API respondeu, mas sem o texto esperado (bloqueio, corte, JSON quebrado)."""


Post = Callable[[str, dict[str, Any], dict[str, str], float], dict[str, Any]]


def _default_post(
    url: str, body: dict[str, Any], headers: dict[str, str], timeout: float
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 — URL fixa
            return json.loads(response.read().decode("utf-8"))
    except (socket.timeout, TimeoutError) as error:
        raise GeminiTimeout(f"A API Gemini passou do tempo: {error}") from error
    except urllib.error.HTTPError as error:
        # A mensagem do Google diz o motivo (chave, crédito, limite); a chave
        # não vai nela, porque segue no cabeçalho.
        detalhe = error.read().decode("utf-8", "replace")[:300]
        raise GeminiUnavailable(f"A API Gemini recusou ({error.code}): {detalhe}") from error
    except urllib.error.URLError as error:
        if isinstance(error.reason, (socket.timeout, TimeoutError)):
            raise GeminiTimeout("A API Gemini passou do tempo.") from error
        raise GeminiUnavailable(f"A API Gemini não respondeu: {error}") from error
    except json.JSONDecodeError as error:
        raise GeminiFormatError("A API Gemini respondeu algo que não é JSON.") from error


class GeminiClient:
    """Uma pergunta, uma resposta: texto e, se houver, uma imagem ou um áudio.

    Temperatura zero, para que a mesma foto dê a mesma leitura — é isso que
    permite medir uma versão do leitor contra o gabarito.
    """

    def __init__(self, *, api_key: str, model: str, post: Post | None = None) -> None:
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY é obrigatória para usar a API Gemini.")
        self._api_key = api_key
        self.model = model
        self._post = post or _default_post
        #: Tokens da última resposta e a soma desde a criação, para medir o
        #: custo de cada leitura.
        self.last_usage: dict[str, Any] = {}
        self.total_tokens = {"entrada": 0, "saida": 0, "chamadas": 0}

    def generate(
        self,
        *,
        prompt: str,
        media: bytes | None = None,
        mime_type: str | None = None,
        schema: dict[str, Any] | None = None,
        timeout: float = 240.0,
    ) -> str:
        parts: list[dict[str, Any]] = []
        if media is not None:
            parts.append(
                {
                    "inline_data": {
                        "mime_type": mime_type or "application/octet-stream",
                        "data": base64.b64encode(media).decode("ascii"),
                    }
                }
            )
        parts.append({"text": prompt})
        config: dict[str, Any] = {"temperature": 0}
        if schema is not None:
            config["responseMimeType"] = "application/json"
            config["responseJsonSchema"] = schema
        reply = self._post(
            ENDPOINT.format(model=self.model),
            {"contents": [{"role": "user", "parts": parts}], "generationConfig": config},
            {"x-goog-api-key": self._api_key},
            timeout,
        )
        self.last_usage = reply.get("usageMetadata") or {}
        self.total_tokens["entrada"] += int(self.last_usage.get("promptTokenCount") or 0)
        self.total_tokens["saida"] += int(self.last_usage.get("candidatesTokenCount") or 0) + int(
            self.last_usage.get("thoughtsTokenCount") or 0
        )
        self.total_tokens["chamadas"] += 1
        return _text(reply)


def _text(reply: dict[str, Any]) -> str:
    candidatos = reply.get("candidates") or []
    if not candidatos:
        motivo = (reply.get("promptFeedback") or {}).get("blockReason", "sem resposta")
        raise GeminiFormatError(f"A API Gemini não devolveu leitura ({motivo}).")
    candidato = candidatos[0]
    motivo = candidato.get("finishReason")
    partes = (candidato.get("content") or {}).get("parts") or []
    texto = "".join(p.get("text", "") for p in partes if not p.get("thought"))
    if motivo not in (None, "STOP"):
        # MAX_TOKENS corta o JSON no meio; SAFETY e afins não trazem texto útil.
        raise GeminiFormatError(f"A API Gemini parou a resposta ({motivo}).")
    if not texto.strip():
        raise GeminiFormatError("A API Gemini respondeu sem texto.")
    return texto
