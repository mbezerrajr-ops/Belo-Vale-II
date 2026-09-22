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
import logging
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from PIL import Image

from app.core.local_url import ensure_local_url
from app.services.event_extraction import EventExtraction
from app.services.image_preprocessing import PreprocessedImage
from app.services.production_files import parse_number_br
from app.services.reading_to_events import (
    SHEET_ORIGIN,
    annotation_events as _annotation_events,
    clean as _clean,
    fold as _fold,
    lines_to_events,
    tidy_transcription,
)
from app.vision.pages import (
    DEFAULT_MAX_SIDE,
    MARGIN_STRIP_NARROW,
    crop_bands,
    crop_left,
    crop_sides,
    crop_top,
    fit,
    load_pages,
)

logger = logging.getLogger(__name__)

EXTRACTOR_NAME = "leitor-local-folha"
#: Muda quando a instrução ou o esquema mudam: a nota do leitor é por versão.
PROMPT_VERSION = "folha-v9"

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

#: A margem é uma resposta de poucas linhas, mas olha a folha inteira.
MARGIN_TIMEOUT = 120.0

#: A primeira leitura carrega o modelo na memória de vídeo; pode demorar.
DEFAULT_TIMEOUT = 600.0


class ReaderUnavailable(RuntimeError):
    """O leitor local não respondeu (desligado, sem modelo, sem memória)."""


class ReaderTimeout(ReaderUnavailable):
    """A leitura passou do tempo: folha longa demais para uma resposta só."""


class ReaderFormatError(ValueError):
    """O leitor respondeu algo fora do esquema da transcrição."""


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
  brinco fica vazio. Nunca use o número da margem de uma linha vizinha.
- ANOTAÇÃO fica na MARGEM DIREITA, na mesma altura da linha, em geral depois
  de uma seta. Copie o que estiver escrito, sem trocar por uma anotação
  parecida. Ignore os tiques (✓, /, 1) que às vezes aparecem ao lado do total.
- ANOTAÇÃO É RARA: a folha inteira costuma ter uma ou duas, e a maioria das
  linhas fica com o campo vazio. Só escreva anotação na linha em que HÁ tinta
  na margem direita naquela altura. Se você só vê uma seta na folha, só uma
  linha recebe anotação — não repita a mesma nas outras.
- Linhas da tabela que ficaram em branco não entram em "linhas". Campo sem
  nada é campo vazio: nunca escreva a palavra "null" como se fosse conteúdo.

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

Campo que não aparecer ou não der para ler: deixe vazio. Nunca invente.
"""

MARGIN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "anotacoes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"linha": _TEXT, "texto": _TEXT},
                "required": ["linha", "texto"],
            },
        }
    },
    "required": ["anotacoes"],
}

MARGIN_PROMPT = """\
Esta imagem junta DUAS TIRAS recortadas da mesma folha de pesagem de leite e
coladas lado a lado, na mesma altura:

- à ESQUERDA, a coluna dos números das linhas da tabela (1., 2., 3., ...);
- à DIREITA, a margem da folha, onde às vezes há algo escrito à mão.

O que está na mesma ALTURA pertence à mesma linha. Responda quais linhas têm
alguma coisa escrita na margem — em geral uma seta seguida de duas ou três
palavras.

Não há uma lista de anotações possíveis: copie o que estiver escrito. Se você
não consegue ler o que há numa altura, deixe aquela linha de fora; não
substitua por uma anotação parecida nem por uma que você imagine provável.

- Anotação é RARA: a folha inteira costuma ter uma ou duas, e muitas folhas
  não têm nenhuma. Se a margem estiver limpa, responda com a lista vazia.
- Liste só as linhas que TÊM escrita na margem. Não liste as outras.
- Não repita a mesma anotação em várias linhas: só se ela estiver escrita
  várias vezes, uma em cada altura.
- Em "linha", o número impresso que está na mesma altura, na tira da
  esquerda.
- Em "texto", o que está escrito, como está escrito.
- Os tiques de conferência ao lado do total (✓, /, 1) não são anotação.
"""

BRINCO_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "brincos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"linha": _TEXT, "brinco": _TEXT},
                "required": ["linha", "brinco"],
            },
        }
    },
    "required": ["brincos"],
}

BRINCO_PROMPT = """\
Esta é a faixa esquerda de um formulário impresso de pesagem de leite.

Você vê duas colunas de números:
- à direita, o número da LINHA, impresso e seguido de ponto (1., 2., 3.);
- à esquerda, fora da tabela, o BRINCO da vaca, escrito à mão.

Para cada linha que TEM um brinco escrito à mão na sua altura, responda o
número da linha e o brinco.

- Copie todos os dígitos como estão escritos, inclusive zeros à esquerda.
- Linha sem nada escrito à esquerda não entra na lista.
- Nunca use o brinco de uma linha vizinha, e nunca invente dígitos.
- Se não der para ler o número de uma linha, deixe essa linha de fora.
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
            # Sem cabeçalho vale o que a transcrição trouxer — que é a fonte
            # pior, e foi por isso que o cabeçalho ganhou chamada própria.
            # Com a GPU carregada essa chamada estoura o prazo, e a data do
            # arquivo sai errada sem ninguém perceber: fica registrado.
            logger.warning("cabeçalho não pôde ser lido à parte; vale a data da transcrição")
            return {}
        return answer if isinstance(answer, dict) else {}

    def read_margin(self, page: PreprocessedImage) -> dict[str, str] | None:
        """As anotações da margem, perguntadas sozinhas: número da linha → texto.

        No meio da transcrição de uma folha inteira, a margem é o campo que o
        modelo mais generaliza — uma seta vira anotação em todas as linhas.
        Perguntada sozinha, numa imagem que cola a coluna dos números ao lado
        da margem, a resposta é curta: só as linhas que têm escrita.

        A tira da direita é fração fixa da largura, e cada foto enquadra a
        folha de um jeito: numa delas ela caiu sobre a coluna TOTAL e a
        resposta veio "26, 34, 33, 30" — os litros. Resposta feita de números
        é sinal de coluna errada, e a folha é perguntada de novo numa tira
        mais estreita, colada à borda.

        `None` quer dizer "não deu para perguntar" (leitor fora do ar, resposta
        fora do esquema): aí vale o que a transcrição trouxer. Lista vazia
        quer dizer "a margem está limpa", e isso apaga o que a transcrição
        inventou.
        """
        larga = self._margin_answer(fit(crop_sides(page), DEFAULT_MAX_SIDE).content)
        if larga is None or not _reads_like_a_column(larga):
            return larga
        estreita = self._margin_answer(
            fit(crop_sides(page, margin=MARGIN_STRIP_NARROW), DEFAULT_MAX_SIDE).content
        )
        if estreita is None:
            return larga
        # Se a tira estreita também só traz números, a folha não tem anotação
        # legível: melhor nenhuma do que a coluna de litros virando observação.
        return {} if _reads_like_a_column(estreita) else estreita

    def _margin_answer(self, image_jpeg: bytes) -> dict[str, str] | None:
        try:
            answer = self._chat(
                prompt=MARGIN_PROMPT,
                schema=MARGIN_SCHEMA,
                image=image_jpeg,
                timeout=MARGIN_TIMEOUT,
            )
        except (ReaderUnavailable, ReaderFormatError):
            logger.warning("margem não pôde ser lida à parte; vale a anotação da transcrição")
            return None
        items = answer.get("anotacoes") if isinstance(answer, dict) else None
        if not isinstance(items, list):
            return None
        found: dict[str, str] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            linha, texto = _line_key(item.get("linha")), _clean(item.get("texto"))
            if linha and texto:
                found[linha] = texto
        return drop_margin_runs(found)

    def read_brincos(self, image_jpeg: bytes) -> dict[str, str] | None:
        """Os brincos da margem esquerda, perguntados sozinhos: linha → brinco.

        Só o formulário impresso: nele o brinco é escrito fora da tabela, numa
        coluna própria, ao lado do número impresso da linha. Perguntar só essa
        faixa dá ao modelo o dobro de pixels por dígito sem perder a âncora.

        `None` quer dizer "não deu para perguntar": vale o que a transcrição
        trouxer.
        """
        try:
            answer = self._chat(
                prompt=BRINCO_PROMPT,
                schema=BRINCO_SCHEMA,
                image=image_jpeg,
                timeout=MARGIN_TIMEOUT,
            )
        except (ReaderUnavailable, ReaderFormatError):
            logger.warning("faixa esquerda não pôde ser lida; vale o brinco da transcrição")
            return None
        items = answer.get("brincos") if isinstance(answer, dict) else None
        if not isinstance(items, list):
            return None
        found: dict[str, str] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            linha, brinco = _line_key(item.get("linha")), _clean(item.get("brinco"))
            if linha and brinco:
                found[linha] = brinco
        return found

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
            # Só o formulário impresso tem margens: o brinco numa coluna à
            # esquerda, fora da tabela, e a anotação solta à direita. São elas
            # que o modelo confunde no meio da transcrição, e cada uma ganha
            # pergunta própria. Na folha manuscrita brinco e anotação estão
            # dentro da própria linha ("3 - 389 ÁGATA → 4 + 5 = 9 → SECAR"):
            # perguntar "o que há na margem" ali não significa nada.
            if layout == "impresso":
                brincos = self.read_brincos(fit(crop_left(page), DEFAULT_MAX_SIDE).content)
                if brincos:
                    reading = apply_brincos(reading, brincos)
                # A margem manda na anotação: linha que ela não cita fica sem
                # anotação nenhuma.
                if (margin := self.read_margin(page)) is not None:
                    reading = apply_margin(reading, margin)
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


#: Quantas linhas SEGUIDAS com a mesma anotação já são invenção. Duas ou três
#: vacas vizinhas mudando de lote juntas acontece na folha; sete linhas
#: seguidas no rabo em branco do formulário, não.
_RUN_LIMIT = 4


def _reads_like_a_column(annotations: dict[str, str]) -> bool:
    """A resposta da margem parece a coluna de litros, não anotações?

    Anotação da fazenda é palavra ("SECA", "2º LOTE", "DOENTE"); a coluna
    TOTAL é número ("26", "34", "20,5"). Três ou mais respostas sem nenhuma
    letra, e a maioria assim, querem dizer que a tira pegou a tabela.
    """
    if len(annotations) < 3:
        return False
    numericas = sum(1 for texto in annotations.values() if not re.search(r"[^\W\d_]", texto))
    return numericas >= 3 and numericas >= len(annotations) / 2


def drop_margin_runs(annotations: dict[str, str]) -> dict[str, str]:
    """Tira da resposta da margem as corridas de linhas seguidas iguais.

    A anotação de verdade é esparsa: numa folha com seis delas, estavam nas
    linhas 2, 8, 10, 11, 13 e 20. Quando o modelo inventa, inventa em fila —
    na mesma folha ele listou 21, 22, 23, 24, 25, 26 e 27 com o mesmo texto,
    todas linhas em branco.
    """
    numeradas = sorted(((int(linha), texto) for linha, texto in annotations.items()), key=lambda p: p[0])
    manter: dict[str, str] = {}
    corrida: list[tuple[int, str]] = []

    def fecha() -> None:
        if len(corrida) < _RUN_LIMIT:
            manter.update({str(linha): texto for linha, texto in corrida})

    for linha, texto in numeradas:
        if corrida and linha == corrida[-1][0] + 1 and _fold(texto) == _fold(corrida[-1][1]):
            corrida.append((linha, texto))
            continue
        fecha()
        corrida = [(linha, texto)]
    fecha()
    return manter


def _line_key(value: Any) -> str:
    """Número da linha como chave, venha "6", "6." ou "nº 6".

    O formulário imprime "6." e o modelo devolve o ponto junto; casar exato
    não colaria a resposta em linha nenhuma.
    """
    return re.sub(r"\D", "", _clean(value) or "")


def apply_margin(reading: dict[str, Any], annotations: dict[str, str]) -> dict[str, Any]:
    """Põe na transcrição as anotações lidas na chamada própria da margem.

    Quem manda é a margem: a linha que ela não cita fica sem anotação, mesmo
    que a transcrição tenha trazido alguma. É o que impede uma seta de virar
    anotação na folha inteira.
    """
    lines = [
        {**line, "anotacao": annotations.get(_line_key(line.get("seq")))}
        for line in reading.get("linhas") or []
    ]
    return {**reading, "linhas": lines}


def apply_brincos(reading: dict[str, Any], brincos: dict[str, str]) -> dict[str, Any]:
    """Troca o brinco das linhas que a faixa esquerda soube ler.

    Ao contrário da margem, aqui a linha que a faixa não cita fica com o que a
    transcrição trouxe: o problema do brinco é dígito trocado, não brinco
    inventado, e apagar o que já se tinha seria perder leitura boa.
    """
    lines = [
        {**line, "brinco": brincos.get(_line_key(line.get("seq"))) or line.get("brinco")}
        for line in reading.get("linhas") or []
    ]
    return {**reading, "linhas": lines}


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
    """A folha lida vira eventos, pelo tradutor que a fala também usa."""
    return lines_to_events(
        transcription,
        extractor_name=EXTRACTOR_NAME,
        extractor_version=extractor_version,
        origem=SHEET_ORIGIN,
    )
