from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLATFORM = ROOT / "plataforma"
sys.path.insert(0, str(PLATFORM))

from state_contract import (
    extract_state_from_html,
    find_del_situation_warnings,
    inject_state_into_html,
    project_state_without_history,
    repair_animal_ids,
    summarize_state,
    validate_state,
)


def without_ids(state):
    result = deepcopy(state)
    for animal in result["vacas"]:
        animal.pop("id", None)
    return result


def load_baseline_state():
    html = (PLATFORM / "platform_ATUAL_publicado.html").read_text(encoding="utf-8")
    return extract_state_from_html(html)


def load_legacy_collision_state():
    state = load_baseline_state()
    legacy_ids = {
        ("CAMBRAIA", "570"): "v570",
        ("MIMOSA", "570"): "v570",
        ("PONTA FINA", "346"): "v346",
        ("PONTA FINA DO ABREU", "346"): "v346",
        ("MALHADINHA", ""): "v",
        ("SERRANA", ""): "v",
    }
    for animal in state["vacas"]:
        legacy_id = legacy_ids.get((animal["nome"], animal["numero"]))
        if legacy_id is not None:
            animal["id"] = legacy_id
    return state


class BaselineStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.state = load_baseline_state()

    def test_baseline_counts_are_preserved(self) -> None:
        summary = summarize_state(self.state)

        self.assertEqual(summary.animal_count, 401)
        self.assertEqual(summary.measurement_count, 152)
        self.assertEqual(
            summary.measurements_by_date,
            {
                "2026-07-22": 107,
                "2026-08-25": 45,
            },
        )
        self.assertEqual(summary.supply_count, 4)
        self.assertEqual(summary.user_count, 2)

    def test_canonical_baseline_has_unique_non_empty_ids(self) -> None:
        report = validate_state(self.state)

        self.assertEqual(report.duplicate_ids, ())
        self.assertNotIn("animal_id_empty", report.errors)
        self.assertNotIn("animal_ids_not_unique", report.errors)

    def test_baseline_reports_del_situation_warnings_without_mutating(self) -> None:
        original = deepcopy(self.state)
        report = validate_state(self.state)
        warnings = find_del_situation_warnings(self.state)

        self.assertEqual(report.del_situation_warning_count, 30)
        self.assertEqual(len(warnings), 30)
        self.assertEqual(
            {warning.code for warning in warnings},
            {"del_empty_while_lactating"},
        )
        self.assertEqual(self.state, original)
        self.assertEqual(self.state["vacas"][0]["nome"], "ÁGATA")


class AnimalIdRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.state = load_legacy_collision_state()

    def test_repair_changes_only_duplicate_ids(self) -> None:
        original = deepcopy(self.state)

        repaired = repair_animal_ids(original)

        self.assertEqual(without_ids(repaired), without_ids(original))
        self.assertEqual(validate_state(repaired).duplicate_ids, ())
        self.assertNotIn("animal_ids_not_unique", validate_state(repaired).errors)

    def test_repair_is_idempotent(self) -> None:
        once = repair_animal_ids(self.state)

        twice = repair_animal_ids(once)

        self.assertEqual(twice, once)

    def test_repair_keeps_all_six_colliding_records(self) -> None:
        id_counts = Counter(animal.get("id") for animal in self.state["vacas"])
        collision_indexes = [
            index
            for index, animal in enumerate(self.state["vacas"])
            if not animal.get("id") or id_counts[animal.get("id")] > 1
        ]

        repaired = repair_animal_ids(self.state)

        self.assertEqual(len(collision_indexes), 6)
        self.assertCountEqual(
            [repaired["vacas"][index]["nome"] for index in collision_indexes],
            [
                "CAMBRAIA",
                "MIMOSA",
                "PONTA FINA",
                "PONTA FINA DO ABREU",
                "MALHADINHA",
                "SERRANA",
            ],
        )
        self.assertEqual(
            len({repaired["vacas"][index]["id"] for index in collision_indexes}),
            6,
        )


class StateProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.state = load_baseline_state()

    def test_template_round_trip_preserves_logical_state(self) -> None:
        template = (PLATFORM / "platform_ATUAL_template.html").read_text(
            encoding="utf-8"
        )
        rendered = inject_state_into_html(template, self.state)

        with tempfile.TemporaryDirectory() as directory:
            generated = Path(directory) / "platform.html"
            generated.write_text(rendered, encoding="utf-8")
            round_trip = extract_state_from_html(
                generated.read_text(encoding="utf-8")
            )

        self.assertEqual(round_trip, self.state)

    def test_projection_removes_only_animal_history(self) -> None:
        projected = project_state_without_history(self.state)

        self.assertEqual(len(projected["vacas"]), 401)
        self.assertTrue(
            all("historico" not in animal for animal in projected["vacas"])
        )
        restored = deepcopy(projected)
        for source, target in zip(
            self.state["vacas"], restored["vacas"], strict=True
        ):
            target["historico"] = source.get("historico", [])
        self.assertEqual(restored, self.state)


class BuildPlatformStateCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.state = load_baseline_state()
        cls.cli = PLATFORM / "build_platform_state.py"

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.cli), *arguments],
            text=True,
            capture_output=True,
            check=False,
        )

    def write_state(self, path: Path, state) -> None:
        path.write_text(
            json.dumps(state, ensure_ascii=False), encoding="utf-8"
        )

    def test_duplicate_ids_exit_one_without_writing_outputs(self) -> None:
        invalid = deepcopy(self.state)
        invalid["vacas"][1]["id"] = invalid["vacas"][0]["id"]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            canonical = root / "canonical.json"
            published = root / "published.html"
            projection = root / "projection.json"
            self.write_state(canonical, invalid)

            result = self.run_cli(
                "generate",
                "--canonical",
                str(canonical),
                "--template",
                str(PLATFORM / "platform_ATUAL_template.html"),
                "--published",
                str(published),
                "--projection",
                str(projection),
            )

            self.assertEqual(result.returncode, 1)
            self.assertFalse(published.exists())
            self.assertFalse(projection.exists())

    def test_valid_state_with_warnings_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            canonical = Path(directory) / "canonical.json"
            self.write_state(canonical, self.state)

            result = self.run_cli(
                "validate", "--canonical", str(canonical)
            )

        self.assertEqual(result.returncode, 0)
        self.assertIn("business_warnings=30", result.stdout)
        self.assertEqual(result.stderr, "")

    def test_malformed_json_exits_two_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            canonical = Path(directory) / "canonical.json"
            canonical.write_text("{not-json", encoding="utf-8")

            result = self.run_cli(
                "validate", "--canonical", str(canonical)
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid JSON", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
