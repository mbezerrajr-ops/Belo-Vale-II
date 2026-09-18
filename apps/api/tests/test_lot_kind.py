"""Tipo de lotação: lote de ordenha × grupo de manejo.

O campo `lote` da baseline mistura duas coisas diferentes. "LOTE 1" é um lote
de ordenha: recebe dieta, tem custo, e é onde a vaca produz. "ENGORDA",
"BEZERREIRO" ou "CAJARANAS" são nomes de áreas e categorias da fazenda — dizem
*onde o animal está*, não como ele é arraçoado.

Tratar os dois como a mesma coisa faz a interface afirmar que uma vaca seca no
bezerreiro está "no lote BEZERREIRO", o que não é verdade: ela não está em
lote nenhum.
"""

import pytest

from app.services.lot_kind import (
    DIET_LOTS,
    KIND_DIET,
    KIND_MANAGEMENT,
    MANAGEMENT_GROUPS,
    classify_lot,
    is_known_lot,
)


class TestClassification:
    def test_numbered_lots_are_diet_lots(self) -> None:
        for lot in ("LOTE 1", "LOTE 2", "LOTE 3"):
            assert classify_lot(lot) == KIND_DIET

    def test_farm_areas_are_management_groups(self) -> None:
        for group in ("ENGORDA", "ENGENHO", "CAJARANAS", "BEZERREIRO", "PALMA"):
            assert classify_lot(group) == KIND_MANAGEMENT

    def test_reproductive_categories_are_management_groups(self) -> None:
        assert classify_lot("PRÉ-PARTO") == KIND_MANAGEMENT
        assert classify_lot("PIQUETES / REPASSE") == KIND_MANAGEMENT

    def test_comparison_ignores_case_accent_and_spacing(self) -> None:
        assert classify_lot("lote 1") == KIND_DIET
        assert classify_lot("  LOTE  1 ") == KIND_DIET
        assert classify_lot("pre-parto") == KIND_MANAGEMENT
        assert classify_lot("Colégio") == KIND_MANAGEMENT
        assert classify_lot("COLEGIO") == KIND_MANAGEMENT

    def test_unknown_value_is_a_management_group(self) -> None:
        """Um nome novo é um lugar até que alguém cadastre dieta para ele.

        Chamar de lote de ordenha o que não tem dieta produziria um custo por
        vaca de zero, que se lê como "não custa nada" em vez de "não sei".
        """
        assert classify_lot("PIQUETE NOVO") == KIND_MANAGEMENT

    def test_empty_has_no_kind(self) -> None:
        assert classify_lot("") is None
        assert classify_lot(None) is None
        assert classify_lot("   ") is None


class TestKnownValues:
    def test_the_thirteen_baseline_values_are_all_known(self) -> None:
        """A baseline usa exatamente estes treze e nada mais."""
        assert len(DIET_LOTS) == 3
        assert len(MANAGEMENT_GROUPS) == 10

    def test_known_lot_recognizes_both_kinds(self) -> None:
        assert is_known_lot("LOTE 1")
        assert is_known_lot("ENGORDA")
        assert not is_known_lot("PIQUETE NOVO")

    def test_diet_and_management_never_overlap(self) -> None:
        assert not (DIET_LOTS & MANAGEMENT_GROUPS)


class TestKindValues:
    def test_kinds_are_the_two_the_database_accepts(self) -> None:
        assert KIND_DIET == "diet"
        assert KIND_MANAGEMENT == "management"


class TestRejectsInvalidInput:
    def test_classify_requires_text(self) -> None:
        with pytest.raises((TypeError, AttributeError)):
            classify_lot(123)  # type: ignore[arg-type]
