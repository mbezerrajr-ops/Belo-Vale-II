"""Leitor local de folhas de pesagem, com um modelo de visão no Ollama.

Duas etapas, e só a primeira usa IA:

A. **Transcrever** — o modelo recebe a página e devolve, num JSON de esquema
   fixo, o que está escrito em cada linha: número, brinco, nome, ordenhas,
   total e anotação. Ele não decide nada; campo ilegível vem vazio.
B. **Traduzir em eventos** (`sheet_to_events`, código nosso, sem IA) — o total
   vira produção na data do cabeçalho, "SECAR" vira ordem de secagem,
   "1º LOTE" vira troca de lote, o resto vira observação.

Depois disso tudo passa pelo mesmo caminho de qualquer leitura: normalização,
associação pelo brinco, alertas e a caixa de revisão. Nada entra no rebanho
sem aprovação.

O modelo roda na infraestrutura da fazenda (decisão do titular: nenhuma foto
sai para provedor externo). `ensure_local_url` recusa qualquer endereço que
não seja a própria máquina ou a rede interna.
"""

from __future__ import annotations

import base64
import ipaddress
import json
import re
import unicodedata
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import date
from typing import Any
from urllib.parse import urlsplit

from app.core.farm_clock import farm_today
from app.services.event_extraction import EventExtraction, ExtractedEvent
from app.services.event_normalization import parse_event_date
from app.vision.pages import load_pages

EXTRACTOR_NAME = "leitor-local-folha"
#: Muda quando a instrução ou o esquema mudam: a nota do leitor é por versão.
PROMPT_VERSION = "folha-v2"

#: Contexto do modelo: imagem + instrução + a transcrição de uma folha cheia.
CONTEXT_TOKENS = 8192

#: A primeira leitura carrega o modelo na memória de vídeo; pode demorar.
DEFAULT_TIMEOUT = 600.0


class ReaderUnavailable(RuntimeError):
    """O leitor local não respondeu (desligado, sem modelo, sem memória)."""


class ReaderFormatError(ValueError):
    """O leitor respondeu algo fora do esquema da transcrição."""


# ------------------------------------------------------------ só endereço local


def ensure_local_url(url: str) -> str:
    """Aceita só a própria máquina e a rede interna. Devolve a URL sem "/" final.

    Nome de serviço sem ponto ("ollama") é aceito: é assim que um contêiner
    acha outro na rede interna do Docker Compose. Domínio com ponto é
    recusado mesmo que resolva para IP interno — não dá para garantir que
    continue assim.
    """
    parts = urlsplit(url or "")
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"Endereço do leitor inválido: {url!r}.")
    host = parts.hostname
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if host == "localhost" or "." not in host:
            return url.rstrip("/")
        raise ValueError(
            f"O leitor precisa rodar na própria infraestrutura; {host} não é endereço interno."
        ) from None
    if address.is_loopback or address.is_private:
        return url.rstrip("/")
    raise ValueError(
        f"O leitor precisa rodar na própria infraestrutura; {host} não é endereço interno."
    )


# --------------------------------------------------------- etapa A: transcrição

_TEXT = {"type": ["string", "null"]}

TRANSCRIPTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "data": _TEXT,
        "lote": _TEXT,
        "linhas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "seq": _TEXT,
                    "brinco": _TEXT,
                    "nome": _TEXT,
                    "manha": _TEXT,
                    "tarde": _TEXT,
                    "total": _TEXT,
                    "anotacao": _TEXT,
                    "trecho": {"type": "string"},
                },
                "required": ["seq", "brinco", "nome", "manha", "tarde", "total", "anotacao", "trecho"],
            },
        },
    },
    "required": ["data", "lote", "linhas"],
}

PROMPT = """\
Você está transcrevendo uma folha manuscrita de pesagem de leite de uma fazenda.
Hoje é {hoje}. A folha é recente: o ano escrito costuma ser o atual ou o anterior.

Cabeçalho: "PESAGEM DO LEITE", a data (dd/mm/aaaa) e o lote (ex.: "3º LOTE").

Cada linha segue o formato:
  nº - BRINCO NOME → MANHÃ + TARDE = TOTAL → ANOTAÇÃO (opcional)
Exemplo: "3 - 389 ÁGATA → 4 + 5 = 9"   ou   "8 - 633 GIGANTE → 2 + 2 = 4 → SECAR"
- "nº" é a contagem da linha (1, 2, 3...), NÃO é o brinco.
- BRINCO é o número logo depois do traço. Às vezes vem depois do nome
  (ex.: "18 - QUARTINHA 406"). Transcreva todos os dígitos como escritos,
  inclusive zeros à esquerda ("016", "011").
- MANHÃ e TARDE são os litros das duas ordenhas; TOTAL é o que vem depois do "=".
  Use vírgula decimal como está escrito ("5,5").
- ANOTAÇÃO é o que vem depois da última seta: "SECAR", "1º LOTE", "SECAR 7 MES.".
  Ela fica à direita, na MESMA altura da linha a que pertence. A maioria das
  linhas não tem anotação: nesse caso use null. Não passe a anotação de uma
  linha para a linha de cima ou de baixo.

Regras:
- Transcreva exatamente o que está escrito. Não corrija contas, não complete
  números, não troque nomes por outros parecidos.
- Se um campo estiver ilegível, use null. Nunca invente.
- Uma entrada em "linhas" para cada linha escrita, na ordem da folha. Não crie
  linhas que não existem.
- Em "trecho", copie a linha inteira como você a leu.
"""


def _default_post(url: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 — URL validada
        return json.loads(response.read().decode("utf-8"))


Post = Callable[[str, dict[str, Any], float], dict[str, Any]]


class OllamaSheetReader:
    """Implementa `EventExtractor` para fotos e PDFs de folhas de pesagem."""

    def __init__(
        self,
        *,
        url: str,
        model: str,
        post: Post | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        today: date | None = None,
    ) -> None:
        self.url = ensure_local_url(url)
        self._today = today
        self.model = model
        self.timeout = timeout
        self._post = post or _default_post

    @property
    def version(self) -> str:
        return f"{self.model}/{PROMPT_VERSION}"

    def transcribe_page(self, image_jpeg: bytes) -> dict[str, Any]:
        body = {
            "model": self.model,
            "stream": False,
            "format": TRANSCRIPTION_SCHEMA,
            # A imagem ocupa boa parte do contexto; o padrão do Ollama (4096)
            # corta a resposta de uma folha cheia no meio do JSON.
            "options": {"temperature": 0, "num_ctx": CONTEXT_TOKENS},
            "messages": [
                {
                    "role": "user",
                    "content": PROMPT.format(hoje=f"{self._today or farm_today():%d/%m/%Y}"),
                    "images": [base64.b64encode(image_jpeg).decode("ascii")],
                }
            ],
        }
        try:
            reply = self._post(f"{self.url}/api/chat", body, self.timeout)
        except (OSError, urllib.error.URLError, TimeoutError) as error:
            raise ReaderUnavailable(f"Leitor local indisponível em {self.url}: {error}") from error
        try:
            content = reply["message"]["content"]
            transcription = json.loads(content)
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise ReaderFormatError(f"Resposta do leitor fora do esquema: {error}") from error
        _check_transcription(transcription)
        return transcription

    def transcribe(self, content: bytes) -> dict[str, Any]:
        """Todas as páginas numa transcrição só, sob o cabeçalho da primeira."""
        pages = [self.transcribe_page(page.content) for page in load_pages(content)]
        first = pages[0]
        header_date = next((p.get("data") for p in pages if p.get("data")), None)
        header_lot = next((p.get("lote") for p in pages if p.get("lote")), None)
        return {
            "data": first.get("data") or header_date,
            "lote": first.get("lote") or header_lot,
            "linhas": [line for page in pages for line in page["linhas"]],
        }

    def extract(self, content: bytes, *, kind: str) -> EventExtraction:
        if kind != "photo":
            raise ValueError(f"O leitor de folhas lê fotos e PDFs, não {kind!r}.")
        return sheet_to_events(self.transcribe(content), extractor_version=self.version)


def _check_transcription(data: Any) -> None:
    if not isinstance(data, dict) or not isinstance(data.get("linhas"), list):
        raise ReaderFormatError("Resposta do leitor sem a lista de linhas.")
    for line in data["linhas"]:
        if not isinstance(line, dict):
            raise ReaderFormatError("Linha da transcrição não é um objeto.")


# ------------------------------------------------------ etapa B: eventos (sem IA)


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


_SECAR = re.compile(r"\bsecar?\b|\bsecagem\b")
_LOT = re.compile(r"(\d+)\s*[ºo°ª]?\s*lote\b|\blote\s*(\d+)")


def _annotation_events(anotacao: str) -> list[tuple[str, dict[str, str | None]]]:
    """"SECAR" → ordem de secagem; "1º LOTE" → troca de lote; o que sobrar
    (ou o que não se reconhece) → observação com o texto original."""
    folded = _fold(anotacao)
    events: list[tuple[str, dict[str, str | None]]] = []
    rest = folded
    if _SECAR.search(folded):
        events.append(("dry_off", {"ordem": "secar"}))
        rest = _SECAR.sub(" ", rest)
    if match := _LOT.search(folded):
        events.append(("lot_change", {"lote": match[1] or match[2]}))
        rest = _LOT.sub(" ", rest)
    if re.sub(r"[\W_]+", "", rest):
        events.append(("note", {"texto": f"Na folha de pesagem: {anotacao}"}))
    return events


def _looks_like_brinco(value: str | None) -> bool:
    return bool(value) and bool(re.fullmatch(r"(B\d+-)?\d+", value.replace(" ", "").upper()))


def _looks_like_name(value: str | None) -> bool:
    return bool(value) and not any(c.isdigit() for c in value)


def tidy_transcription(transcription: dict[str, Any]) -> dict[str, Any]:
    """Correções óbvias, sem adivinhar: hoje só a troca brinco ↔ nome.

    "18 - QUARTINHA 406" tem o nome antes do número, e o modelo às vezes
    devolve os dois na ordem da folha. Número no nome e palavra no brinco é
    troca certa; qualquer outra combinação fica como veio.
    """
    lines = []
    for line in transcription.get("linhas") or []:
        brinco, nome = _clean(line.get("brinco")), _clean(line.get("nome"))
        if _looks_like_name(brinco) and _looks_like_brinco(nome):
            line = {**line, "brinco": nome, "nome": brinco}
        lines.append(line)
    return {**transcription, "linhas": lines}


def sheet_to_events(transcription: dict[str, Any], *, extractor_version: str) -> EventExtraction:
    reference = parse_event_date(_clean(transcription.get("data")), reference=None)
    events: list[ExtractedEvent] = []
    for line in tidy_transcription(transcription)["linhas"]:
        brinco = _clean(line.get("brinco"))
        nome = _clean(line.get("nome"))
        manha, tarde, total = (_clean(line.get(k)) for k in ("manha", "tarde", "total"))
        evidence = {"text": _clean(line.get("trecho")) or "", "linha": _clean(line.get("seq"))}

        def add(event_type: str, fields: dict[str, str | None]) -> None:
            events.append(
                ExtractedEvent(
                    event_type=event_type, brinco=brinco, nome=nome,
                    fields=fields, evidence=evidence,
                )
            )

        if total or manha or tarde:
            fields: dict[str, str | None] = {"producao": total}
            if manha and tarde:
                fields["parcelas"] = f"{manha} + {tarde}"
            add("production", fields)
        if anotacao := _clean(line.get("anotacao")):
            for event_type, fields in _annotation_events(anotacao):
                add(event_type, fields)

    return EventExtraction(
        events=events,
        extractor_name=EXTRACTOR_NAME,
        extractor_version=extractor_version,
        reference_date=reference,
    )
