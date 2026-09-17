"""Normalização canônica de brinco.

O brinco é a única chave de matching automático do rebanho, então a forma
canônica precisa ser determinística e não pode inventar, completar ou corrigir
um valor lido — apenas padronizar espaçamento e caixa.
"""

from app.services.brinco import normalize_brinco


class TestNormalizeBrinco:
    def test_strips_surrounding_whitespace(self) -> None:
        assert normalize_brinco("  B2-008  ") == "B2-008"

    def test_collapses_internal_whitespace(self) -> None:
        # Caso real da baseline: "B2- 008"
        assert normalize_brinco("B2- 008") == "B2-008"
        assert normalize_brinco("B2 -  008") == "B2-008"

    def test_uppercases(self) -> None:
        # Caso real da baseline: "B1-016VD"
        assert normalize_brinco("b1-016vd") == "B1-016VD"

    def test_empty_becomes_none(self) -> None:
        assert normalize_brinco("") is None
        assert normalize_brinco("   ") is None

    def test_none_stays_none(self) -> None:
        assert normalize_brinco(None) is None

    def test_preserves_purely_numeric_brinco(self) -> None:
        # 179 brincos da baseline são numéricos e são brincos físicos reais:
        # não podem ser descartados nem reformatados.
        assert normalize_brinco("389") == "389"
        assert normalize_brinco("1009") == "1009"

    def test_does_not_pad_or_reformat(self) -> None:
        # Normalizar não é corrigir: 026 e 26 são valores diferentes e
        # continuam diferentes.
        assert normalize_brinco("026") == "026"
        assert normalize_brinco("26") == "26"

    def test_is_idempotent(self) -> None:
        for raw in ("B2- 008", "  b1-016vd ", "389", ""):
            once = normalize_brinco(raw)
            assert normalize_brinco(once) == once

    def test_placeholder_is_not_treated_as_valid_brinco(self) -> None:
        # "B2-XXX" é um placeholder ilegível na baseline (SERRANA), não um
        # brinco. Não pode virar chave de matching automático.
        assert normalize_brinco("B2-XXX") is None
        assert normalize_brinco("b2-xxx") is None

    def test_unreadable_marker_variants_are_rejected(self) -> None:
        assert normalize_brinco("XXX") is None
        assert normalize_brinco("???") is None
        assert normalize_brinco("---") is None
