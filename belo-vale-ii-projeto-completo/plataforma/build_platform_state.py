from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from state_contract import (
    StateSummary,
    ValidationReport,
    extract_state_from_html,
    inject_state_into_html,
    project_state_without_history,
    repair_animal_ids,
    summarize_state,
    validate_state,
)


EXPECTED_BASELINE = StateSummary(
    animal_count=401,
    measurement_count=152,
    measurements_by_date={"2026-07-22": 107, "2026-08-25": 45},
    supply_count=4,
    user_count=2,
)


class StateValidationError(ValueError):
    pass


def load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def encode_json(state: Mapping[str, Any], *, pretty: bool = True) -> str:
    indent = 2 if pretty else None
    return json.dumps(state, ensure_ascii=False, indent=indent) + "\n"


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            delete=False,
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        ) as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def require_valid(state: Mapping[str, Any]) -> ValidationReport:
    report = validate_state(state, expected=EXPECTED_BASELINE)
    if report.errors:
        raise StateValidationError(
            "state validation failed: " + ", ".join(report.errors)
        )
    return report


def print_summary(state: Mapping[str, Any], report: ValidationReport) -> None:
    summary = summarize_state(state)
    print(f"animals={summary.animal_count}")
    print(f"measurements={summary.measurement_count}")
    for date, count in summary.measurements_by_date.items():
        print(f"{date}={count}")
    print(f"supplies={summary.supply_count}")
    print(f"users={summary.user_count}")
    print(f"structural_errors={len(report.errors)}")
    print(f"business_warnings={report.del_situation_warning_count}")


def bootstrap(published: Path, canonical: Path) -> None:
    source = extract_state_from_html(published.read_text(encoding="utf-8"))
    state = repair_animal_ids(source)
    report = require_valid(state)
    atomic_write_text(canonical, encode_json(state))
    print_summary(state, report)


def validate(canonical: Path) -> None:
    state = load_json_object(canonical)
    report = require_valid(state)
    print_summary(state, report)


def generate(
    canonical: Path,
    template: Path,
    published: Path,
    projection: Path,
) -> None:
    state = load_json_object(canonical)
    report = require_valid(state)
    template_text = template.read_bytes().decode("utf-8")
    published_text = inject_state_into_html(template_text, state)
    projection_text = encode_json(
        project_state_without_history(state), pretty=False
    )
    atomic_write_text(published, published_text)
    atomic_write_text(projection, projection_text)
    print_summary(state, report)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and build the legacy platform state artifacts."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap_parser = subparsers.add_parser("bootstrap")
    bootstrap_parser.add_argument("--published", type=Path, required=True)
    bootstrap_parser.add_argument("--canonical", type=Path, required=True)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--canonical", type=Path, required=True)

    generate_parser = subparsers.add_parser("generate")
    generate_parser.add_argument("--canonical", type=Path, required=True)
    generate_parser.add_argument("--template", type=Path, required=True)
    generate_parser.add_argument("--published", type=Path, required=True)
    generate_parser.add_argument("--projection", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "bootstrap":
            bootstrap(args.published, args.canonical)
        elif args.command == "validate":
            validate(args.canonical)
        else:
            generate(
                args.canonical,
                args.template,
                args.published,
                args.projection,
            )
    except StateValidationError as error:
        print(str(error), file=sys.stderr)
        return 1
    except json.JSONDecodeError as error:
        print(
            f"invalid JSON: {error.msg} "
            f"(line {error.lineno}, column {error.colno})",
            file=sys.stderr,
        )
        return 2
    except (OSError, UnicodeError, ValueError) as error:
        print(f"input error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
