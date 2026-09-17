from __future__ import annotations

from collections import Counter
from copy import deepcopy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLATFORM = ROOT / "plataforma"
sys.path.insert(0, str(PLATFORM))

from state_contract import (
    extract_state_from_html,
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

    def test_baseline_reports_duplicate_or_empty_ids(self) -> None:
        report = validate_state(self.state)

        self.assertEqual(report.duplicate_ids, ("v", "v346", "v570"))
        self.assertIn("animal_ids_not_unique", report.errors)

    def test_baseline_reports_del_situation_warnings_without_mutating(self) -> None:
        report = validate_state(self.state)

        self.assertEqual(report.del_situation_warning_count, 30)
        self.assertEqual(self.state["vacas"][0]["nome"], "ÁGATA")


class AnimalIdRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.state = load_baseline_state()

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


if __name__ == "__main__":
    unittest.main()
