import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("build_manual_conflicts_report.py")
SPEC = importlib.util.spec_from_file_location("manual_conflicts_report", MODULE_PATH)
REPORT = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(REPORT)


class ManualConflictsReportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.document = REPORT.build_html()

    def test_unmatched_records_are_preserved_instead_of_classified(self) -> None:
        self.assertIn(
            "Cadastros preservados sem nova medição neste arquivo — 141",
            self.document,
        )
        self.assertIn(
            "a medição e o histórico anteriores continuam válidos",
            self.document,
        )
        self.assertNotIn("Animais ausentes no PDF recente", self.document)
        self.assertNotIn("☐ Vendido", self.document)

    def test_summary_separates_checks_observations_and_preserved_records(self) -> None:
        self.assertIn("43</strong>verificações manuais reais", self.document)
        self.assertIn("27</strong>coincidências não conclusivas", self.document)
        self.assertIn("141</strong>cadastros preservados sem ação", self.document)

    def test_project_decisions_include_recommendation_and_rationale(self) -> None:
        self.assertIn(
            "Decisões de negócio e contrato dos arquivos",
            self.document,
        )
        for heading in (
            "Pergunta",
            "Orientação técnica",
            "Argumento",
            "Decisão final",
            "Responsável/data",
        ):
            self.assertIn(heading, self.document)
        for question in (
            "Todo arquivo submetido deverá conter todo o rebanho?",
            "Conflito significa substituição?",
            "O que acontece quando um animal não aparece no arquivo?",
            "Como desfazer uma importação incorreta?",
        ):
            self.assertIn(question, self.document)


if __name__ == "__main__":
    unittest.main()
