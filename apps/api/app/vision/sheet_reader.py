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
import io
import ipaddress
import json
import re
import unicodedata
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from PIL import Image

from app.services.event_extraction import EventExtraction, ExtractedEvent
from app.services.image_preprocessing import PreprocessedImage
from app.services.event_normalization import parse_event_date
from app.services.production_files import parse_number_br
from app.vision.pages import (
    DEFAULT_MAX_SIDE,
    crop_bands,
    crop_top,
    fit,
    load_pages,
)

EXTRACTOR_NAME = "leitor-local-folha"
#: Muda quando a instrução ou o esquema mudam: a nota do leitor é por versão.
PROMPT_VERSION = "folha-v7"

#: Contexto do modelo: imagem + instrução + a transcrição de uma folha cheia.
#: Uma folha de 48 linhas não cabia em 8192 e a resposta vinha cortada.
CONTEXT_TOKENS = 12288

#: Semente fixa: com temperatura 0 a GPU ainda pode trocar um token entre
#: rodadas e mudar a leitura inteira; a semente deixa a mesma foto dar a
#: mesma leitura.
SEED = 0

#: Resolução da segunda leitura, quando a primeira sai incoerente.
RETRY_MAX_SIDE = 1000

#: Tempo de uma página inteira. Estourou: a folha é longa (48 linhas na do 1º
#: lote) e a resposta inteira não sai; então ela é lida em faixas.
PAGE_TIMEOUT = 240.0

#: O cabeçalho é uma resposta de dez palavras: não precisa de tempo de folha.
HEADER_TIMEOUT = 90.0

#: A primeira leitura carrega o modelo na memória de vídeo; pode demorar.
DEFAULT_TIMEOUT = 600.0


class ReaderUnavailable(RuntimeError):
    """O leitor local não respondeu (desligado, sem modelo, sem memória)."""


class ReaderTimeout(ReaderUnavailable):
    """A leitura passou do tempo: folha longa demais para uma resposta só."""


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

#: Formatos de folha que o leitor conhece.
LAYOUTS = ("impresso", "manuscrito")

_LINE_FIELDS = ("nome", "manha", "tarde", "total", "anotacao")


def _schema(first: tuple[str, str]) -> dict[str, Any]:
    """Esquema da transcrição. A ordem das chaves importa: o modelo as
    preenche nessa ordem, e ela tem de seguir a folha da esquerda para a
    direita — senão ele põe o número da margem no campo errado."""
    keys = (*first, *_LINE_FIELDS)
    return {
        "type": "object",
        "properties": {
            "data": _TEXT,
            "lote": _TEXT,
            "linhas": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {**{key: _TEXT for key in keys}, "trecho": {"type": "string"}},
                    "required": [*keys, "trecho"],
                },
            },
        },
        "required": ["data", "lote", "linhas"],
    }


SCHEMAS: dict[str, dict[str, Any]] = {
    # Formulário impresso: o brinco está na margem esquerda, antes do nº impresso.
    "impresso": _schema(("brinco", "numero_da_linha")),
    # Folha manuscrita: "nº - brinco nome".
    "manuscrito": _schema(("numero_da_linha", "brinco")),
}

_COMMON_RULES = """Regras:
- Brinco: todos os dígitos como escritos, inclusive zeros à esquerda ("016").
- Litros com vírgula decimal como escritos ("5,5").
- Data e lote: copie exatamente como escritos no cabeçalho.
- Leia linha por linha, alinhando pela altura: brinco, nome, litros e
  anotação de uma entrada têm de estar na mesma linha da folha.
- Não corrija contas, não complete números, não troque nomes por parecidos.
- Campo ilegível: null. Nunca invente linhas nem valores.
- Cada linha é independente: não repita a anotação ou o brinco de outra linha.
- Em "trecho", copie a linha como você a leu.
"""

PROMPTS: dict[str, str] = {
    "impresso": """Você está transcrevendo o formulário impresso de pesagem de leite
"CONTROLE LEITEIRO BELO VALE II", preenchido à mão.

- Cabeçalho: "LOTE: ___" e "DATA: __/__/__".
- Tabela com as colunas VACA/Nº, MANHÃ, TARDE e TOTAL, e linhas numeradas
  (1, 2, 3...) já impressas. O número impresso vai em "numero_da_linha";
  ele NÃO é o brinco.
- Na coluna VACA/Nº está o NOME da vaca.
- O BRINCO está escrito à mão na MARGEM ESQUERDA, fora da tabela, na mesma
  altura da linha. Algumas linhas não têm brinco na margem: nesse caso o
  brinco é null. Nunca use o número da margem de uma linha vizinha.
- ANOTAÇÃO fica na MARGEM DIREITA, na mesma altura da linha, geralmente depois
  de uma seta: "→ 2º LOT", "→ SECA", "DOENTE". Ignore os tiques (✓, /, 1)
  que às vezes aparecem ao lado do total.
- Linhas da tabela que ficaram em branco não entram em "linhas".

""" + _COMMON_RULES,
    "manuscrito": """Você está transcrevendo uma folha pautada de pesagem de leite, escrita à mão.

Cabeçalho: "PESAGEM DO LEITE", a data (dd/mm/aaaa) e o lote (ex.: "3º LOTE").

Cada linha segue o formato:
  nº - BRINCO NOME → MANHÃ + TARDE = TOTAL → ANOTAÇÃO (opcional)
Exemplo: "3 - 389 ÁGATA → 4 + 5 = 9"   ou   "8 - 633 GIGANTE → 2 + 2 = 4 → SECAR"
- "nº" é a contagem da linha e vai em "numero_da_linha"; NÃO é o brinco.
- BRINCO é o número logo depois do traço. Às vezes vem depois do nome
  (ex.: "18 - QUARTINHA 406").
- MANHÃ e TARDE são os litros das duas ordenhas; TOTAL vem depois do "=".
- ANOTAÇÃO é o que vem depois da última seta: "SECAR", "1º LOTE", "SECAR 7 MES.".
  A maioria das linhas não tem anotação: use null.

""" + _COMMON_RULES,
}

HEADER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"data": _TEXT, "lote": _TEXT},
    "required": ["data", "lote"],
}

HEADER_PROMPT = """\
Este é o alto de uma folha de pesagem de leite de uma fazenda, preenchida à mão.

Transcreva só duas coisas:
- DATA: como está escrita (ex.: "25/08/2026" ou "22/07/26"). Copie os dígitos
  exatamente; não corrija o ano nem complete nada.
- LOTE: o lote escrito no cabeçalho (ex.: "1º LOTE", "2º LOTE", "3º LOTE").
  Olhe bem o dígito: 2 e 3 se parecem nesta letra.

Campo que não aparecer ou não der para ler: null. Nunca invente.
"""

_LAYOUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"formato": {"type": "string", "enum": list(LAYOUTS)}},
    "required": ["formato"],
}

_LAYOUT_PROMPT = """Esta imagem é uma folha de pesagem de leite. Qual o formato?
- "impresso": formulário impresso "CONTROLE LEITEIRO", com tabela de colunas
  VACA/Nº, MANHÃ, TARDE e TOTAL e linhas numeradas já impressas.
- "manuscrito": folha pautada toda escrita à mão, "PESAGEM DO LEITE", com
  linhas como "3 - 389 ÁGATA → 4 + 5 = 9".
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
    ) -> None:
        self.url = ensure_local_url(url)
        self.model = model
        self.timeout = timeout
        self._post = post or _default_post

    @property
    def version(self) -> str:
        return f"{self.model}/{PROMPT_VERSION}"

    def _chat(
        self, *, prompt: str, schema: dict[str, Any], image: bytes, timeout: float | None = None
    ) -> Any:
        body = {
            "model": self.model,
            "stream": False,
            "format": schema,
            # A imagem ocupa boa parte do contexto; o padrão do Ollama (4096)
            # corta a resposta de uma folha cheia no meio do JSON.
            "options": {"temperature": 0, "seed": SEED, "num_ctx": CONTEXT_TOKENS},
            "messages": [
                {
                    "role": "user",
                    # Sem "hoje é ...": a dica fez o modelo escrever a data de hoje
                    # num formulário de 22/07/26. A data vem só da folha.
                    "content": prompt,
                    "images": [base64.b64encode(image).decode("ascii")],
                }
            ],
        }
        try:
            reply = self._post(f"{self.url}/api/chat", body, timeout or self.timeout)
        except TimeoutError as error:
            raise ReaderTimeout(f"O leitor passou do tempo em {self.url}: {error}") from error
        except (OSError, urllib.error.URLError) as error:
            raise ReaderUnavailable(f"Leitor local indisponível em {self.url}: {error}") from error
        try:
            return json.loads(reply["message"]["content"])
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise ReaderFormatError(f"Resposta do leitor fora do esquema: {error}") from error

    def read_header(self, image_jpeg: bytes) -> dict[str, Any]:
        """Data e lote, perguntados sozinhos no recorte do alto da folha.

        No meio da transcrição de 48 linhas eles saíam errados — o cabeçalho
        "2º LOTE" virou "3º LOTE" em duas leituras seguidas, e as 47 linhas
        daquela página deixaram de casar com o gabarito.
        """
        try:
            answer = self._chat(
                prompt=HEADER_PROMPT,
                schema=HEADER_SCHEMA,
                image=image_jpeg,
                timeout=HEADER_TIMEOUT,
            )
        except (ReaderUnavailable, ReaderFormatError):
            return {}  # sem cabeçalho, vale o que a transcrição trouxer
        return answer if isinstance(answer, dict) else {}

    def classify_page(self, image_jpeg: bytes) -> str:
        """Formulário impresso ou folha manuscrita. Resposta estranha: impresso,
        o formato em uso na fazenda."""
        answer = self._chat(prompt=_LAYOUT_PROMPT, schema=_LAYOUT_SCHEMA, image=image_jpeg)
        layout = answer.get("formato") if isinstance(answer, dict) else None
        return layout if layout in LAYOUTS else "impresso"

    def transcribe_page(
        self, image_jpeg: bytes, layout: str | None = None, *, timeout: float | None = None
    ) -> dict[str, Any]:
        layout = layout or self.classify_page(image_jpeg)
        transcription = self._chat(
            prompt=PROMPTS[layout], schema=SCHEMAS[layout], image=image_jpeg, timeout=timeout
        )
        _check_transcription(transcription)
        return {
            **transcription,
            "_formato": layout,
            "linhas": [_from_model_keys(line) for line in transcription["linhas"]],
        }

    def _bands(self, page: PreprocessedImage, layout: str, max_side: int) -> dict[str, Any]:
        """Folha longa: lida em duas faixas com sobreposição. Cada resposta é
        curta o bastante para sair no tempo; as linhas se juntam pelo número
        impresso, que a sobreposição repete.

        As faixas saem da página **original** e só então são reduzidas: assim
        cada uma chega ao modelo com o dobro de pixels por letra.
        """
        readings = [
            self.transcribe_page(fit(band, max_side).content, layout)
            for band in crop_bands(page)
        ]
        return merge_bands(readings)

    def _page(self, page: PreprocessedImage, layout: str, max_side: int) -> dict[str, Any]:
        try:
            return self.transcribe_page(
                fit(page, max_side).content, layout, timeout=PAGE_TIMEOUT
            )
        except (ReaderTimeout, ReaderFormatError):
            # Tempo estourado ou resposta cortada: a folha é longa demais para
            # uma resposta só.
            return self._bands(page, layout, max_side)

    def transcribe(self, content: bytes) -> dict[str, Any]:
        """Todas as páginas numa transcrição só, sob o cabeçalho da primeira.

        Cada página é conferida (`incoherence`): se a leitura sai incoerente
        — o mesmo brinco em várias linhas, somas que não fecham —, é lida de
        novo em outra resolução, e fica a mais coerente das duas.
        """
        # A página fica na resolução original; os recortes (cabeçalho, faixas)
        # saem dela e só então são reduzidos, para não reduzir duas vezes.
        pages = load_pages(content, max_side=None)
        readings = []
        for page in pages:
            header = self.read_header(fit(crop_top(page), DEFAULT_MAX_SIDE).content)
            layout = self.classify_page(fit(page, DEFAULT_MAX_SIDE).content)
            reading = self._page(page, layout, DEFAULT_MAX_SIDE)
            if _needs_retry(reading):
                second = self._page(page, layout, RETRY_MAX_SIDE)
                if incoherence(second) < incoherence(reading):
                    reading = second
            # O cabeçalho lido à parte vale mais que o que veio no meio das linhas.
            readings.append({
                **reading,
                "data": _clean(header.get("data")) or reading.get("data"),
                "lote": _clean(header.get("lote")) or reading.get("lote"),
            })
        first = readings[0]
        return {
            "data": first.get("data") or next((r.get("data") for r in readings if r.get("data")), None),
            "lote": first.get("lote") or next((r.get("lote") for r in readings if r.get("lote")), None),
            "_formato": first.get("_formato"),
            # A página vai junto: cada folha recomeça a numeração em 1.
            "linhas": [
                # O lote escrito na página acompanha a linha: é por ele que a
                # leitura se alinha ao gabarito, já que as páginas de um PDF
                # podem vir fora da ordem dos lotes.
                {"pagina": number, "lote_pagina": reading.get("lote"), **line}
                for number, reading in enumerate(readings, start=1)
                for line in reading["linhas"]
            ],
        }

    def extract(self, content: bytes, *, kind: str) -> EventExtraction:
        if kind != "photo":
            raise ValueError(f"O leitor de folhas lê fotos e PDFs, não {kind!r}.")
        return sheet_to_events(self.transcribe(content), extractor_version=self.version)


def _from_model_keys(line: dict[str, Any]) -> dict[str, Any]:
    """Chaves do esquema do modelo → transcrição interna (`seq`)."""
    if "numero_da_linha" not in line:
        return line
    converted = {k: v for k, v in line.items() if k != "numero_da_linha"}
    converted["seq"] = line["numero_da_linha"]
    return converted


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
#: "1º LOTE", "LOTE 2" e a abreviação da margem do formulário, "2º LOT".
_LOT = re.compile(r"(\d+)\s*[ºo°ª]?\s*lote?\b|\blote?\s*(\d+)")


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


#: O que faz de uma linha uma leitura. Brinco sozinho não: é o número da
#: margem ao lado de uma linha vazia ou riscada.
_CONTENT_FIELDS = ("nome", "manha", "tarde", "total", "anotacao")


def tidy_transcription(transcription: dict[str, Any]) -> dict[str, Any]:
    """Correções óbvias, sem adivinhar: descarta linha em branco do
    formulário, desfaz a troca brinco ↔ nome e apaga brinco "0".

    "18 - QUARTINHA 406" tem o nome antes do número, e o modelo às vezes
    devolve os dois na ordem da folha. Número no nome e palavra no brinco é
    troca certa; qualquer outra combinação fica como veio.
    """
    lines = []
    for line in transcription.get("linhas") or []:
        brinco, nome = _clean(line.get("brinco")), _clean(line.get("nome"))
        if not any(_clean(line.get(k)) for k in _CONTENT_FIELDS):
            continue  # linha do formulário que ficou em branco
        if _looks_like_name(brinco) and _looks_like_brinco(nome):
            line = {**line, "brinco": nome, "nome": brinco}
        if brinco and re.fullmatch(r"0+", brinco):
            line = {**line, "brinco": None}  # o modelo pôs "0" onde não havia brinco
        anotacao = _clean(line.get("anotacao"))
        if anotacao and not re.search(r"[^\W\d_]", anotacao):
            # Só números ou sinais: o tique de conferência ao lado do total.
            line = {**line, "anotacao": None}
        lines.append(line)
    return {**transcription, "linhas": lines}


def merge_bands(readings: list[dict[str, Any]]) -> dict[str, Any]:
    """Junta as faixas de uma página: a linha repetida na sobreposição entra
    uma vez só, valendo a primeira leitura dela."""
    lines: list[dict[str, Any]] = []
    seen: set[str] = set()
    for reading in readings:
        for line in reading.get("linhas") or []:
            key = _clean(line.get("seq")) or ""
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            lines.append(line)
    first = readings[0] if readings else {}
    return {
        **first,
        "data": next((r.get("data") for r in readings if r.get("data")), None),
        "lote": next((r.get("lote") for r in readings if r.get("lote")), None),
        "linhas": lines,
    }


def incoherence(transcription: dict[str, Any]) -> int:
    """Quanto a leitura se contradiz, sem olhar a folha: brincos repetidos na
    mesma página (repetição do modelo ou margem desalinhada) e linhas em que
    manhã + tarde não dá o total. Zero não prova que está certa; muito prova
    que não está."""
    lines = tidy_transcription(transcription)["linhas"]
    seen: set[str] = set()
    score = 0
    for line in lines:
        brinco = _clean(line.get("brinco"))
        if brinco:
            key = brinco.upper()
            if key in seen:
                score += 1
            seen.add(key)
        parts = [parse_number_br(line.get(k)) for k in ("manha", "tarde", "total")]
        if all(value is not None for value in parts) and abs(parts[0] + parts[1] - parts[2]) > 0.01:
            score += 1
    return score


def _needs_retry(transcription: dict[str, Any]) -> bool:
    """Uma ou outra soma errada é da própria folha; mais que isso, relê."""
    lines = len(tidy_transcription(transcription)["linhas"])
    return incoherence(transcription) > max(1, lines // 10)


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
