from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLATFORM = ROOT / "plataforma"
sys.path.insert(0, str(PLATFORM))

from state_contract import extract_state_from_html, summarize_state, validate_state


class BaselineStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        html = (PLATFORM / "platform_ATUAL_publicado.html").read_text(encoding="utf-8")
        cls.state = extract_state_from_html(html)

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


if __name__ == "__main__":
    unittest.main()
