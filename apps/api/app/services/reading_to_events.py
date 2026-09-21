"""Leitura → eventos, sem IA.

Um leitor (visão, fala) devolve uma estrutura intermediária simples: uma
lista de linhas, cada uma com brinco, nome, as duas ordenhas, o total e uma
anotação, tudo como texto, como foi lido. Este módulo é o que transforma isso
em eventos — o total vira produção, "SECAR" vira ordem de secagem, "1º LOTE"
vira troca de lote, e o que não se reconhece vira observação com o texto
original.

Nada aqui usa modelo nenhum: são regras nossas, escritas para serem lidas e
testadas. É de propósito que a parte que decide o que os dados significam não
dependa de IA — a IA transcreve, o código traduz.

A folha de pesagem e a fala do curral produzem a mesma estrutura, então
passam pelo mesmo tradutor. O que muda entre elas é só de onde veio o texto
da observação (`origem`).
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Any

from app.services.event_extraction import EventExtraction, ExtractedEvent
from app.services.event_normalization import parse_event_date

#: O modelo às vezes ESCREVE a palavra em vez de deixar o campo vazio. Numa
#: foto real ele pôs "null" nas 14 linhas em branco do formulário, e elas
#: viraram 14 produções fantasma com litros "null". Vazio é vazio, escrito
#: por extenso ou não.
WRITTEN_EMPTY = frozenset({"null", "none", "nulo", "nula", "n/a", "na", "-", "--", "---"})


def fold(text: str) -> str:
    """Minúsculas e sem acento: é assim que o código compara texto lido."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def clean(value: Any) -> str | None:
    """Texto como foi lido, sem espaço sobrando. Vazio (inclusive escrito por
    extenso) vira `None`."""
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    if not text or fold(text) in WRITTEN_EMPTY:
        return None
    return text


SECAR = re.compile(r"\bsecar?\b|\bsecagem\b")
#: "1º LOTE", "LOTE 2" e a abreviação da margem do formulário, "2º LOT".
#: O "º" manuscrito sai do modelo como ":", "o" ou ".": "2: LOT" é a mesma
#: troca de lote, e não pode virar observação só por causa da grafia — na
#: caixa de Revisão uma é campo preenchido, a outra é texto solto.
LOT = re.compile(r"(\d+)\s*[ºo°ª:.=-]?\s*lote?\b|\blote?\s*(\d+)")

#: De onde veio a anotação, para quem revisa saber o que está lendo.
SHEET_ORIGIN = "Na folha de pesagem"


def annotation_events(
    anotacao: str, *, origem: str = SHEET_ORIGIN
) -> list[tuple[str, dict[str, str | None]]]:
    """"SECAR" → ordem de secagem; "1º LOTE" → troca de lote; o que sobrar
    (ou o que não se reconhece) → observação com o texto original."""
    folded = fold(anotacao)
    events: list[tuple[str, dict[str, str | None]]] = []
    rest = folded
    if SECAR.search(folded):
        events.append(("dry_off", {"ordem": "secar"}))
        rest = SECAR.sub(" ", rest)
    if match := LOT.search(folded):
        events.append(("lot_change", {"lote": match[1] or match[2]}))
        rest = LOT.sub(" ", rest)
    if re.sub(r"[\W_]+", "", rest):
        events.append(("note", {"texto": f"{origem}: {anotacao}"}))
    return events


def looks_like_brinco(value: str | None) -> bool:
    return bool(value) and bool(re.fullmatch(r"(B\d+-)?\d+", value.replace(" ", "").upper()))


def looks_like_name(value: str | None) -> bool:
    return bool(value) and not any(c.isdigit() for c in value)


#: O que faz de uma linha uma leitura. Brinco sozinho não: é o número da
#: margem ao lado de uma linha vazia ou riscada.
CONTENT_FIELDS = ("nome", "manha", "tarde", "total", "anotacao")


def tidy_transcription(transcription: dict[str, Any]) -> dict[str, Any]:
    """Correções óbvias, sem adivinhar: descarta linha em branco do
    formulário, desfaz a troca brinco ↔ nome e apaga brinco "0".

    "18 - QUARTINHA 406" tem o nome antes do número, e o modelo às vezes
    devolve os dois na ordem da folha. Número no nome e palavra no brinco é
    troca certa; qualquer outra combinação fica como veio.
    """
    lines = []
    for line in transcription.get("linhas") or []:
        brinco, nome = clean(line.get("brinco")), clean(line.get("nome"))
        if not any(clean(line.get(k)) for k in CONTENT_FIELDS):
            continue  # linha do formulário que ficou em branco
        if looks_like_name(brinco) and looks_like_brinco(nome):
            line = {**line, "brinco": nome, "nome": brinco}
        if brinco and re.fullmatch(r"0+", brinco):
            line = {**line, "brinco": None}  # o modelo pôs "0" onde não havia brinco
        anotacao = clean(line.get("anotacao"))
        if anotacao and not re.search(r"[^\W\d_]", anotacao):
            # Só números ou sinais: o tique de conferência ao lado do total.
            line = {**line, "anotacao": None}
        lines.append(line)
    return {**transcription, "linhas": drop_repeated_annotation(lines)}


#: A partir de quantas linhas iguais, e de que fatia da página, a anotação
#: deixa de ser leitura e passa a ser repetição do modelo. Seis linhas porque
#: um lote pequeno pode mudar junto de verdade; 60% porque a margem anotada
#: de ponta a ponta não acontece na folha, e acontece no modelo.
REPEAT_LINES = 6
REPEAT_SHARE = 0.6


def drop_repeated_annotation(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apaga a anotação que aparece na folha inteira.

    A anotação fica na margem direita, solta, longe da linha a que pertence.
    O modelo às vezes copia a mesma para todas as linhas: numa foto real uma
    seta "→ 3º LOTE" virou 23 trocas de lote, e um "SECA" virou 27 ordens de
    secagem. Uma ordem de secar falsa é o erro mais caro que pode chegar na
    caixa de Revisão, e vinte e três delas afogam quem revisa.

    O que se perde: a folha em que muitas vacas realmente foram marcadas
    igual entra sem a marca. O que não se perde: a produção da tabela, a
    leitura crua (guardada no `raw_response` da execução) e a foto, que fica
    ao lado das propostas para conferência.
    """
    counts = Counter(fold(anotacao) for line in lines if (anotacao := clean(line.get("anotacao"))))
    repeated = {
        text
        for text, count in counts.items()
        if count >= REPEAT_LINES and count >= REPEAT_SHARE * len(lines)
    }
    if not repeated:
        return lines
    return [
        {**line, "anotacao": None}
        if (anotacao := clean(line.get("anotacao"))) and fold(anotacao) in repeated
        else line
        for line in lines
    ]


def lines_to_events(
    transcription: dict[str, Any],
    *,
    extractor_name: str,
    extractor_version: str,
    origem: str = SHEET_ORIGIN,
    reference_date: Any = None,
) -> EventExtraction:
    """As linhas lidas viram eventos, um a um.

    `reference_date` é a data que vale para a leitura inteira. A folha traz a
    dela no cabeçalho; a fala não tem cabeçalho, e quem chama informa a data
    da fazenda. Em qualquer caso, quem revisa pode corrigir o arquivo inteiro
    de uma vez.
    """
    reference = reference_date or parse_event_date(clean(transcription.get("data")), reference=None)
    events: list[ExtractedEvent] = []
    for line in tidy_transcription(transcription)["linhas"]:
        brinco = clean(line.get("brinco"))
        nome = clean(line.get("nome"))
        manha, tarde, total = (clean(line.get(k)) for k in ("manha", "tarde", "total"))
        evidence = {"text": clean(line.get("trecho")) or "", "linha": clean(line.get("seq"))}
        confidence = line.get("confianca") if isinstance(line.get("confianca"), dict) else {}

        def add(event_type: str, fields: dict[str, str | None]) -> None:
            events.append(
                ExtractedEvent(
                    event_type=event_type, brinco=brinco, nome=nome,
                    fields=fields, evidence=evidence, confidence=confidence,
                )
            )

        if total or manha or tarde:
            fields: dict[str, str | None] = {"producao": total}
            if manha and tarde:
                fields["parcelas"] = f"{manha} + {tarde}"
            add("production", fields)
        if anotacao := clean(line.get("anotacao")):
            for event_type, fields in annotation_events(anotacao, origem=origem):
                add(event_type, fields)

    return EventExtraction(
        events=events,
        extractor_name=extractor_name,
        extractor_version=extractor_version,
        reference_date=reference,
    )
