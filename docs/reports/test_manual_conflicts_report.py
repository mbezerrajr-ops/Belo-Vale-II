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
        self.assertIn("30</strong>verificações manuais obrigatórias", self.document)
        self.assertIn("13</strong>observações de nome, não bloqueiam", self.document)
        self.assertIn("27</strong>coincidências não conclusivas", self.document)
        self.assertIn("141</strong>cadastros preservados sem ação", self.document)
        # A contagem antiga somava divergências de nome às verificações
        # obrigatórias, tratando diferença de nome como problema de
        # identidade. Sob a regra de que o brinco é a única identidade,
        # isso não bloqueia mais nada.
        self.assertNotIn("43</strong>verificações manuais reais", self.document)

    def test_report_declares_brinco_as_sole_identity_key(self) -> None:
        self.assertIn(
            "O brinco é a única chave de identidade operacional", self.document
        )
        self.assertIn(
            "Nome é informação descritiva, não identificadora", self.document
        )
        self.assertIn(
            "não deve ser usado para localizar, casar ou fundir animais",
            self.document,
        )

    def test_name_divergences_are_not_ranked_as_identity_risk(self) -> None:
        # A tabela de ordem de resolução não pode mais descrever divergência
        # de nome como um problema de identidade: o brinco já resolveu a
        # identidade antes de o nome ser sequer avaliado.
        self.assertNotIn("Identidade incorreta", self.document)
        self.assertIn(
            "Divergências de nome — 13 casos, não bloqueiam a migração",
            self.document,
        )
        self.assertIn(
            "o brinco já confirmou a identidade deste animal",
            self.document,
        )

    def test_lot_change_is_documented_as_temporal_history(self) -> None:
        self.assertIn(
            "A vaca pode mudar de lote ao longo do tempo",
            self.document,
        )
        self.assertIn(
            "Como registrar a mudança de lote de um animal?",
            self.document,
        )
        self.assertIn("histórico de lotação", self.document)

    def test_closing_criterion_references_only_del_alerts(self) -> None:
        self.assertIn(
            "Os 30 alertas de DEL são a única verificação obrigatória desta "
            "baseline",
            self.document,
        )
        self.assertIn(
            "As divergências de nome e as coincidências de nome são "
            "observações e não bloqueiam a migração",
            self.document,
        )
        self.assertNotIn(
            "as 43\n      verificações obrigatórias e as decisões de contrato",
            self.document,
        )

    def test_version_is_1_2(self) -> None:
        self.assertIn("Versão 1.2", self.document)
        self.assertNotIn("Versão 1.1", self.document)

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
