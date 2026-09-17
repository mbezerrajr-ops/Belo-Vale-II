from __future__ import annotations

import builtins
from copy import deepcopy
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PLATFORM = ROOT / "plataforma"
IMPORTER = PLATFORM / "import_relatorio_animais.py"
sys.path.insert(0, str(PLATFORM))

from import_relatorio_animais import (
    apply_report_rows,
    read_pdf_rows,
    render_import_report,
)
from state_contract import summarize_state


def sample_state():
    return {
        "vacas": [
            {
                "id": "v101",
                "numero": "101",
                "nome": "MIMOSA",
                "lote": "LOTE 1",
                "nascimento": "",
                "parto": "2026-01-01",
                "peso": "",
                "media": 18.0,
                "del": 200,
                "situacao": "Em lactação",
                "ultimaMedicao": "2026-08-25",
                "status": "Ativo",
                "historico": [
                    {"data": "2026-07-22", "producao": 20.0},
                    {"data": "2026-08-25", "producao": 18.0},
                ],
            }
        ],
        "insumos": [],
        "usuarios": [],
        "precoLeite": 2.59,
    }


REPORT_ROWS = [
    {
        "brinco": "101",
        "nome": "MIMOSA",
        "lote": "Lote 2",
        "data": "01/09/2026",
        "delx": "16",
    },
    {
        "brinco": "B2-202",
        "nome": "NOVA",
        "lote": "Lote 3",
        "data": "",
        "delx": "",
    },
]


class ImportSafetyTests(unittest.TestCase):
    def test_module_import_does_not_require_pdfplumber(self) -> None:
        original_import = builtins.__import__

        def import_without_pdfplumber(name, *args, **kwargs):
            if name == "pdfplumber":
                raise ModuleNotFoundError("pdfplumber intentionally unavailable")
            return original_import(name, *args, **kwargs)

        module_name = "import_relatorio_animais_under_test"
        spec = importlib.util.spec_from_file_location(module_name, IMPORTER)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            with patch("builtins.__import__", side_effect=import_without_pdfplumber):
                spec.loader.exec_module(module)
        finally:
            sys.modules.pop(module_name, None)

        self.assertTrue(callable(module.apply_report_rows))


class ApplyReportRowsTests(unittest.TestCase):
    def test_reapplying_rows_is_idempotent_and_preserves_history(self) -> None:
        original = sample_state()
        history = deepcopy(original["vacas"][0]["historico"])

        first = apply_report_rows(original, REPORT_ROWS)
        second = apply_report_rows(first.state, REPORT_ROWS)

        self.assertEqual(len(first.state["vacas"]), 2)
        self.assertEqual(len(second.state["vacas"]), 2)
        self.assertEqual(first.new_animal_count, 1)
        self.assertEqual(second.new_animal_count, 0)
        self.assertEqual(first.state["vacas"][0]["historico"], history)
        self.assertEqual(second.state["vacas"][0]["historico"], history)
        self.assertEqual(
            [animal["id"] for animal in second.state["vacas"]],
            [animal["id"] for animal in first.state["vacas"]],
        )
        self.assertEqual(original, sample_state())

    def test_real_pdf_is_idempotent_against_canonical_state(self) -> None:
        report_path = next((ROOT.parent / "docs").glob("REL*ANIMAIS.pdf"))
        canonical_path = PLATFORM / "state_canonical.json"
        canonical = json.loads(canonical_path.read_text(encoding="utf-8"))

        rows = read_pdf_rows(report_path)
        first = apply_report_rows(deepcopy(canonical), rows)
        second = apply_report_rows(first.state, rows)
        report = render_import_report(first)

        self.assertEqual(len(rows), 260)
        self.assertEqual(second.new_animal_count, 0)
        self.assertEqual(summarize_state(first.state), summarize_state(canonical))
        self.assertEqual(second.state, first.state)
        self.assertIn("--- Avisos DEL/situação: 30", report)


if __name__ == "__main__":
    unittest.main()
