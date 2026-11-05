"""Dá nota ao leitor local contra folhas reais já conferidas.

Uso::

    uv run python -m app.core.evaluate_reader --samples ../../docs/Treinamento-VC

Para cada amostra (PDF, JPEG ou PNG) com um gabarito ao lado
(`<nome>.gabarito.json`, no mesmo formato da transcrição), lê a folha com o
modelo local e conta, campo a campo, o que saiu certo. Grava ao lado:

- `<nome>.transcricao.json` — o que o modelo leu;
- `<nome>.leitura.json` — os eventos, prontos para
  `python -m app.core.load_proposals --file <nome>.leitura.json`.

Folhas cujos dados já foram lançados dispensam gabarito: com
`--records-date AAAA-MM-DD`, todas as fotos (filtradas por `--pattern`) são
comparadas com as medições do dia no banco — brinco, nome e total — e o
comando diz quantas vacas chegariam à revisão com a vaca certa.

As amostras são dados reais da fazenda e ficam fora do Git
(`docs/Treinamento-VC/` está no .gitignore). Nada sai da máquina: o leitor só
aceita endereço local.
"""

from __future__ import annotations

import argparse
import atexit
import asyncio
import json
import sys
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.gemini import GeminiClient
from app.db.models import Animal, OfficialMeasurement, Farm
from app.services.event_normalization import parse_event_date
from app.services.brinco import normalize_brinco
from app.services.event_proposals import (
    SIMILAR_NAME,
    name_similarity,
    name_suggestions,
    suggest_animals,
)
from app.services.production_files import parse_number_br
from app.vision.sheet_reader import (
    GeminiSheetReader,
    OllamaSheetReader,
    ReaderFormatError,
    ReaderUnavailable,
    sheet_to_events,
    tidy_transcription,
)

FIELDS = ("brinco", "nome", "manha", "tarde", "total", "anotacao")
_SAMPLE_SUFFIXES = (".pdf", ".jpg", ".jpeg", ".png")


def _fold(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).upper()


def _same(field_name: str, read: Any, truth: Any) -> bool:
    if field_name in ("manha", "tarde", "total"):
        return parse_number_br(read) == parse_number_br(truth)
    if field_name == "brinco":
        # Brinco é identidade: "016" e "16" são diferentes (ver brinco.py).
        clean = lambda v: None if v is None else "".join(str(v).split()).upper() or None  # noqa: E731
        return clean(read) == clean(truth)
    return _fold(read) == _fold(truth)


@dataclass
class Score:
    lines_expected: int = 0
    missed: int = 0
    invented: int = 0
    header_date_ok: bool = False
    header_lot_ok: bool = False
    correct: dict[str, int] = field(default_factory=lambda: dict.fromkeys(FIELDS, 0))
    #: (linha, campo, esperado, lido)
    errors: list[tuple[str, str, Any, Any]] = field(default_factory=list)


def _lote_number(value: Any) -> str | None:
    """"3º LOTE", "3º" e "Lote 3" viram "3"."""
    digits = "".join(c for c in str(value or "") if c.isdigit())
    return digits or None


def _page_labels(lines: list[dict[str, Any]]) -> dict[int, str]:
    """Rótulo de cada página física, pelo lote escrito nela — mas pela
    posição quando esse lote colide com o de uma página anterior.

    Cada folha recomeça a numeração em 1, então a página entra na chave; usar
    o LOTE escrito nela (em vez da posição) resolve o PDF de 25/08, cujas
    páginas vêm fora de ordem (3º lote, 1º, 2º). Mas o leitor às vezes erra o
    cabeçalho — uma página do 2º lote foi lida como "3º LOTE", igual à
    página do 3º lote de verdade — e duas páginas com o mesmo rótulo
    misturariam suas linhas na comparação. A segunda a reivindicar um lote já
    visto cai para o próprio número da página, que nunca colide.
    """
    labels: dict[int, str] = {}
    seen: set[str] = set()
    for line in lines:
        pagina = line.get("pagina")
        if pagina is None or pagina in labels:
            continue
        lote = _lote_number(line.get("lote_pagina"))
        # "p{página}" nunca colide com um número de lote (sempre dígitos
        # puros) — nem quando a página física é a 3 e o lote colidido também
        # é "3", como aconteceu na leitura real de 25/08.
        label = lote if lote and lote not in seen else f"p{pagina}"
        labels[pagina] = label
        seen.add(label)
    return labels


def _key(line: dict[str, Any], index: int, page_labels: dict[int, str] | None = None) -> str:
    """Identidade da linha para alinhar leitura e gabarito."""
    seq = line.get("seq")
    numero = str(seq).strip() if seq not in (None, "") else f"#{index + 1}"
    pagina = line.get("pagina")
    label = (page_labels or {}).get(pagina) if pagina is not None else None
    if label is None:
        label = _lote_number(line.get("lote_pagina")) or pagina
    return f"{label}.{numero}" if label else numero


def compare(reading: dict[str, Any], truth: dict[str, Any]) -> Score:
    """Alinha as linhas pelo número da linha (ou pela posição) e compara."""
    score = Score()
    score.header_date_ok = parse_event_date(reading.get("data"), reference=None) == parse_event_date(
        truth.get("data"), reference=None
    ) and parse_event_date(truth.get("data"), reference=None) is not None
    score.header_lot_ok = _fold(reading.get("lote")) == _fold(truth.get("lote"))

    truth_lines = truth.get("linhas") or []
    reading_lines = reading.get("linhas") or []
    truth_labels = _page_labels(truth_lines)
    reading_labels = _page_labels(reading_lines)
    expected = {_key(line, i, truth_labels): line for i, line in enumerate(truth_lines)}
    got = {_key(line, i, reading_labels): line for i, line in enumerate(reading_lines)}
    score.lines_expected = len(expected)
    score.invented = len(set(got) - set(expected))
    for key, truth_line in expected.items():
        read_line = got.get(key)
        if read_line is None:
            score.missed += 1
            continue
        for name in FIELDS:
            if _same(name, read_line.get(name), truth_line.get(name)):
                score.correct[name] += 1
            else:
                score.errors.append((key, name, truth_line.get(name), read_line.get(name)))
    return score


def _report(name: str, score: Score, seconds: float) -> str:
    total = score.lines_expected
    rows = [
        f"== {name}  ({seconds:.0f}s)",
        f"   data do cabeçalho: {'ok' if score.header_date_ok else 'ERRADA'}"
        f" · lote: {'ok' if score.header_lot_ok else 'errado'}",
        f"   linhas: {total} esperadas · {score.missed} perdidas · {score.invented} inventadas",
    ]
    for name_ in FIELDS:
        pct = 100 * score.correct[name_] / total if total else 0
        rows.append(f"   {name_:<9} {score.correct[name_]}/{total}  ({pct:.0f}%)")
    for key, field_name, want, got in score.errors:
        rows.append(f"   - linha {key}: {field_name} esperado {want!r}, lido {got!r}")
    return "\n".join(rows)


# ------------------------------------------------ contra o que já foi lançado


def _core(brinco: Any) -> str | None:
    """"B2-117" e "117" são a mesma vaca para a nota (a revisão sugere o
    prefixo; ver `event_proposals.brinco_variants`)."""
    if brinco in (None, ""):
        return None
    text = "".join(str(brinco).split()).upper()
    core = text.split("-")[-1]
    return core.lstrip("0") or core


@dataclass
class RecordScore:
    #: Linhas lidas (com algum conteúdo).
    lines: int = 0
    #: Linhas cujo brinco é de uma vaca lançada no dia.
    brinco_found: int = 0
    #: Dessas, quantas com o total igual ao lançado.
    total_ok: int = 0
    #: Dessas, quantas com o nome parecido com o do cadastro.
    nome_ok: int = 0
    #: Vacas lançadas no dia que nenhuma linha achou pelo brinco.
    missing: list[dict[str, Any]] = field(default_factory=list)
    #: Vacas achadas por mais de uma linha (sinal de brinco desalinhado).
    duplicated: list[dict[str, Any]] = field(default_factory=list)
    #: Linhas sem vaca do dia pelo brinco.
    unmatched: list[dict[str, Any]] = field(default_factory=list)
    #: (linha, campo, lançado, lido) das linhas achadas.
    errors: list[tuple[str, str, Any, Any]] = field(default_factory=list)


def compare_with_records(lines: list[dict[str, Any]], records: list[dict[str, Any]]) -> RecordScore:
    """Nota das folhas de um dia contra as medições já lançadas nesse dia.

    Sem gabarito à mão: a verdade é o banco (brinco, nome e total por vaca).
    Manhã, tarde e anotações não ficam no banco e não entram nesta nota.
    """
    score = RecordScore()
    by_core = {_core(record["brinco"]): record for record in records}
    hits: dict[str | None, int] = {}
    for index, line in enumerate(lines):
        score.lines += 1
        record = by_core.get(_core(line.get("brinco")))
        if record is None:
            score.unmatched.append(line)
            continue
        key = _key(line, index)
        score.brinco_found += 1
        hits[_core(record["brinco"])] = hits.get(_core(record["brinco"]), 0) + 1
        if parse_number_br(line.get("total")) == record["total"]:
            score.total_ok += 1
        else:
            score.errors.append((key, "total", record["total"], line.get("total")))
        if name_similarity(line.get("nome"), record["nome"]) >= SIMILAR_NAME:
            score.nome_ok += 1
        else:
            score.errors.append((key, "nome", record["nome"], line.get("nome")))
    score.missing = [r for r in records if _core(r["brinco"]) not in hits]
    score.duplicated = [r for r in records if hits.get(_core(r["brinco"]), 0) > 1]
    return score


@dataclass
class ReviewReach:
    #: Vacas do dia que chegam à revisão já associadas ou em 1º lugar nas sugestões.
    reached: int = 0
    #: Das alcançadas, quantas pedem um toque: o brinco lido é de outra vaca
    #: (nome divergente, com alerta) e a certa aparece em "Ou é esta".
    one_tap: int = 0
    #: Linhas que apontam uma vaca já apontada por outra linha: erro certo.
    repeated: int = 0
    #: Linhas que apontam uma vaca sem medição com brinco no dia: erro de
    #: leitura ou ficha duplicada no cadastro (a medição está na cópia sem
    #: brinco). Sem gabarito por linha, fica à parte.
    outside_day: int = 0


def review_reach(
    lines: list[dict[str, Any]], records: list[dict[str, Any]], animals: list[Any]
) -> ReviewReach:
    """O que o revisor vê, com as regras da caixa de Revisão: associação só
    pelo brinco exato; sem ele, a primeira sugestão (prefixo, nome parecido,
    brinco a um dígito)."""
    day = {_core(record["brinco"]) for record in records}
    by_brinco = {animal.brinco: animal for animal in animals if animal.brinco}
    reach = ReviewReach()
    seen: set[str | None] = set()
    for line in lines:
        brinco = normalize_brinco(line.get("brinco"))
        animal = by_brinco.get(brinco) if brinco else None
        tapped = False
        if animal is not None and name_similarity(line.get("nome"), animal.name) < SIMILAR_NAME:
            # Nome divergente: a caixa alerta e oferece a vaca do nome lido.
            others = [a for a in name_suggestions(animals, line.get("nome")) if a is not animal]
            if others:
                animal, tapped = others[0], True
        if animal is None:
            suggestions = suggest_animals(animals, line.get("brinco"), line.get("nome"), limit=1)
            animal = suggestions[0] if suggestions else None
        if animal is None:
            continue
        core = _core(animal.brinco)
        if core in seen:
            reach.repeated += 1
        elif core in day:
            seen.add(core)
            reach.reached += 1
            reach.one_tap += tapped
        else:
            reach.outside_day += 1
    return reach


def _records_report(
    day: date,
    photos: int,
    seconds: float,
    records: list,
    score: RecordScore,
    reach: ReviewReach | None = None,
) -> str:
    found = len(records) - len(score.missing)
    pct = lambda n, d: f"{100 * n / d:.0f}%" if d else "—"  # noqa: E731
    rows = [
        f"== {photos} fotos de {day:%d/%m/%Y}  ({seconds:.0f}s)",
        f"   vacas lançadas no dia: {len(records)} · linhas lidas: {score.lines}",
        f"   brinco    {found}/{len(records)} vacas do dia achadas ({pct(found, len(records))})",
        f"   total     {score.total_ok}/{score.brinco_found} das linhas achadas "
        f"({pct(score.total_ok, score.brinco_found)})",
        f"   nome      {score.nome_ok}/{score.brinco_found} das linhas achadas "
        f"({pct(score.nome_ok, score.brinco_found)})",
        f"   repetidas {len(score.duplicated)} · linhas sem vaca do dia: {len(score.unmatched)}",
    ]
    if reach is not None:
        rows.append(
            f"   revisão   {reach.reached}/{len(records)} vacas do dia com a vaca certa associada "
            f"ou em 1º lugar ({pct(reach.reached, len(records))}), {reach.one_tap} delas com "
            "um toque em \"Ou é esta\""
        )
        rows.append(
            f"             {reach.repeated} linhas apontam vaca já apontada (erro certo) · "
            f"{reach.outside_day} apontam vaca sem medição com brinco no dia (a conferir)"
        )
    for record in score.duplicated:
        rows.append(f"   - repetida: {record['brinco']} {record['nome']}")
    for line in score.unmatched:
        rows.append(f"   - sem vaca do dia: brinco {line.get('brinco')!r} nome {line.get('nome')!r}")
    for record in score.missing:
        rows.append(f"   - não achada: {record['brinco']} {record['nome']} ({record['total']:g} L)")
    for key, field_name, want, got in score.errors:
        rows.append(f"   - linha {key}: {field_name} lançado {want!r}, lido {got!r}")
    return "\n".join(rows)


async def _evaluation_farm(session, farm_id):
    if farm_id is not None:
        if await session.get(Farm, farm_id) is None: raise ValueError("Fazenda não encontrada para avaliação.")
        return farm_id
    farms = list(await session.scalars(select(Farm.id).limit(2)))
    if len(farms) != 1: raise ValueError("Informe --farm-id para avaliar uma única fazenda.")
    return farms[0]


async def _load_herd_async(farm_id=None) -> list[Any]:
    engine = create_async_engine(get_settings().postgres_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine)() as session:
            farm_id = await _evaluation_farm(session, farm_id)
            return list(await session.scalars(select(Animal).where(Animal.farm_id == farm_id)))
    finally:
        await engine.dispose()


def load_herd(farm_id=None) -> list[Any]:
    """O cadastro inteiro, para simular as sugestões da revisão."""
    return asyncio.run(_load_herd_async(farm_id))


async def _load_records_async(day: date, farm_id=None) -> list[dict[str, Any]]:
    engine = create_async_engine(get_settings().postgres_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine)() as session:
            farm_id = await _evaluation_farm(session, farm_id)
            rows = await session.execute(
                select(Animal.brinco, Animal.name, OfficialMeasurement.values)
                .join(Animal, Animal.id == OfficialMeasurement.animal_id)
                .where(
                    OfficialMeasurement.measured_on == day,
                    OfficialMeasurement.status == "active",
                    Animal.brinco.is_not(None),
                    Animal.farm_id == farm_id,
                )
            )
            return [
                {"brinco": brinco, "nome": name, "total": float(producao_of_values(values))}
                for brinco, name, values in rows
                if producao_of_values(values) is not None
            ]
    finally:
        await engine.dispose()


def producao_of_values(values: dict[str, Any] | None) -> float | None:
    value = (values or {}).get("producao")
    return None if value is None else float(value)


def load_records(day: date, farm_id=None) -> list[dict[str, Any]]:
    """Medições ativas do dia, com o brinco e o nome do cadastro."""
    return asyncio.run(_load_records_async(day, farm_id))


# -------------------------------------------------------------------- comando

Transcriber = Callable[[bytes], dict[str, Any]]


def _read(sample: Path, transcriber: Transcriber, version: str, reuse: bool) -> dict[str, Any]:
    """Lê a amostra e grava a transcrição e os eventos ao lado dela."""
    saved = sample.with_name(f"{sample.stem}.transcricao.json")
    if reuse and saved.exists():
        previous = json.loads(saved.read_text(encoding="utf-8"))
        if previous.get("_leitor") == version:
            return previous
    reading = {**transcriber(sample.read_bytes()), "_leitor": version}
    saved.write_text(json.dumps(reading, ensure_ascii=False, indent=2), encoding="utf-8")
    extraction = sheet_to_events(reading, extractor_version=version)
    sample.with_name(f"{sample.stem}.leitura.json").write_text(
        json.dumps(extraction.to_raw(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return reading


def _print_tokens(client: GeminiClient) -> None:
    print(f"   tokens    {client.total_tokens}")


def main(
    argv: list[str] | None = None,
    *,
    transcriber: Transcriber | None = None,
    records: list[dict[str, Any]] | None = None,
    herd: list[Any] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--samples", required=True, type=Path, help="Pasta com as amostras.")
    parser.add_argument("--url", default=None, help="Endereço do Ollama (padrão: READER_URL).")
    parser.add_argument("--model", default=None, help="Modelo (padrão: READER_MODEL).")
    parser.add_argument(
        "--provider",
        choices=("ollama", "gemini"),
        default=None,
        help="Quem lê (padrão: READER_PROVIDER; 'gemini' usa GEMINI_API_KEY).",
    )
    parser.add_argument(
        "--records-date",
        type=date.fromisoformat,
        default=None,
        help="Compara com as medições já lançadas nesta data (AAAA-MM-DD), sem gabarito.",
    )
    parser.add_argument(
        "--pattern", default="*", help="Só as amostras cujo nome casa com o padrão (ex.: 'cont_*')."
    )
    parser.add_argument(
        "--reuse",
        action="store_true",
        help="Reaproveita a transcrição salva da mesma versão do leitor, sem ler de novo.",
    )
    parser.add_argument("--farm-id", type=UUID, help="Fazenda cujas medições e cadastro serão comparados.")
    args = parser.parse_args(argv)

    version = "externo"
    if transcriber is None:
        settings = get_settings()
        provider = args.provider or settings.reader_provider
        reader: OllamaSheetReader
        if provider == "gemini":
            key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else ""
            reader = GeminiSheetReader(
                client=GeminiClient(api_key=key, model=args.model or settings.reader_model)
            )
            # O custo vem dos tokens: imprime a soma no fim, qualquer que seja
            # a saída do comando.
            atexit.register(_print_tokens, reader.client)
        else:
            reader = OllamaSheetReader(
                url=args.url or settings.reader_url, model=args.model or settings.reader_model
            )
        transcriber = reader.transcribe
        version = reader.version

    candidates = sorted(
        path for path in args.samples.glob(args.pattern) if path.suffix.lower() in _SAMPLE_SUFFIXES
    )
    if args.records_date is None:
        candidates = [p for p in candidates if p.with_name(f"{p.stem}.gabarito.json").exists()]
    if not candidates:
        print(f"Nenhuma amostra em {args.samples} para comparar.", file=sys.stderr)
        return 2

    print(f"leitor: {version}")
    started = time.monotonic()
    pooled: list[dict[str, Any]] = []
    for sample in candidates:
        page_started = time.monotonic()
        try:
            reading = _read(sample, transcriber, version, args.reuse)
        except ReaderUnavailable as error:
            print(f"erro: {error}", file=sys.stderr)
            return 2
        except ReaderFormatError as error:
            # Uma folha ilegível não pode derrubar a nota das outras.
            print(f"-- {sample.name}: leitura recusada ({error})")
            continue
        # A nota é do que chega à revisão: depois das correções óbvias.
        tidy = tidy_transcription(reading)
        if args.records_date is None:
            truth = json.loads(
                sample.with_name(f"{sample.stem}.gabarito.json").read_text(encoding="utf-8")
            )
            print(_report(sample.name, compare(tidy, truth), time.monotonic() - page_started))
        else:
            print(
                f"-- {sample.name}: data {tidy.get('data')!r} · lote {tidy.get('lote')!r} · "
                f"{len(tidy['linhas'])} linhas ({time.monotonic() - page_started:.0f}s)"
            )
            pooled.extend(tidy["linhas"])

    if args.records_date is not None:
        day_records = records if records is not None else load_records(args.records_date, args.farm_id)
        animals = herd if herd is not None else (load_herd(args.farm_id) if records is None else None)
        score = compare_with_records(pooled, day_records)
        reach = review_reach(pooled, day_records, animals) if animals is not None else None
        print(
            _records_report(
                args.records_date,
                len(candidates),
                time.monotonic() - started,
                day_records,
                score,
                reach,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
