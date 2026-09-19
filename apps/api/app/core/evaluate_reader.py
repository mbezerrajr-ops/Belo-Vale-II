"""Dá nota ao leitor local contra folhas reais já conferidas.

Uso::

    uv run python -m app.core.evaluate_reader --samples ../../docs/Treinamento-VC

Para cada amostra (PDF, JPEG ou PNG) com um gabarito ao lado
(`<nome>.gabarito.json`, no mesmo formato da transcrição), lê a folha com o
modelo local e conta, campo a campo, o que saiu certo. Grava ao lado:

- `<nome>.transcricao.json` — o que o modelo leu;
- `<nome>.leitura.json` — os eventos, prontos para
  `python -m app.core.load_proposals --file <nome>.leitura.json`.

As amostras são dados reais da fazenda e ficam fora do Git
(`docs/Treinamento-VC/` está no .gitignore). Nada sai da máquina: o leitor só
aceita endereço local.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.services.event_normalization import parse_event_date
from app.services.production_files import parse_number_br
from app.vision.sheet_reader import (
    OllamaSheetReader,
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


def _key(line: dict[str, Any], index: int) -> str:
    seq = line.get("seq")
    return str(seq).strip() if seq not in (None, "") else f"#{index + 1}"


def compare(reading: dict[str, Any], truth: dict[str, Any]) -> Score:
    """Alinha as linhas pelo número da linha (ou pela posição) e compara."""
    score = Score()
    score.header_date_ok = parse_event_date(reading.get("data"), reference=None) == parse_event_date(
        truth.get("data"), reference=None
    ) and parse_event_date(truth.get("data"), reference=None) is not None
    score.header_lot_ok = _fold(reading.get("lote")) == _fold(truth.get("lote"))

    expected = {_key(line, i): line for i, line in enumerate(truth.get("linhas") or [])}
    got = {_key(line, i): line for i, line in enumerate(reading.get("linhas") or [])}
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


Transcriber = Callable[[bytes], dict[str, Any]]


def main(argv: list[str] | None = None, *, transcriber: Transcriber | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--samples", required=True, type=Path, help="Pasta com as amostras.")
    parser.add_argument("--url", default=None, help="Endereço do Ollama (padrão: READER_URL).")
    parser.add_argument("--model", default=None, help="Modelo (padrão: READER_MODEL).")
    args = parser.parse_args(argv)

    version = "externo"
    if transcriber is None:
        settings = get_settings()
        reader = OllamaSheetReader(
            url=args.url or settings.reader_url, model=args.model or settings.reader_model
        )
        transcriber = reader.transcribe
        version = reader.version

    samples = sorted(
        path for path in args.samples.iterdir()
        if path.suffix.lower() in _SAMPLE_SUFFIXES
        and path.with_name(f"{path.stem}.gabarito.json").exists()
    )
    if not samples:
        print(f"Nenhuma amostra com gabarito em {args.samples}.", file=sys.stderr)
        return 2

    print(f"leitor: {version}")
    for sample in samples:
        truth = json.loads(sample.with_name(f"{sample.stem}.gabarito.json").read_text(encoding="utf-8"))
        started = time.monotonic()
        try:
            reading = transcriber(sample.read_bytes())
        except ReaderUnavailable as error:
            print(f"erro: {error}", file=sys.stderr)
            return 2
        seconds = time.monotonic() - started
        sample.with_name(f"{sample.stem}.transcricao.json").write_text(
            json.dumps(reading, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        extraction = sheet_to_events(reading, extractor_version=version)
        sample.with_name(f"{sample.stem}.leitura.json").write_text(
            json.dumps(extraction.to_raw(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        # A nota é do que chega à revisão: depois das correções óbvias.
        print(_report(sample.name, compare(tidy_transcription(reading), truth), seconds))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
