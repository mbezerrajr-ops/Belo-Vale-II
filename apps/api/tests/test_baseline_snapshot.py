"""Leitura e validação do estado canônico legado.

Domínio puro: nenhuma conexão de banco, nenhum efeito colateral. O objetivo é
que qualquer divergência da baseline seja detectada *antes* de qualquer
escrita.
"""

import json
from datetime import date

import pytest

from app.services.baseline_snapshot import (
    EXPECTED_BASELINE,
    BaselineValidationError,
    parse_baseline,
    validate_snapshot,
)


def _animal(**overrides) -> dict:
    base = {
        "id": "v389",
        "numero": "389",
        "nome": "ÁGATA",
        "lote": "LOTE 3",
        "nascimento": "",
        "parto": "2026-01-20",
        "peso": "",
        "media": 12.0,
        "situacao": "Em lactação",
        "ultimaMedicao": "2026-07-22",
        "status": "Ativo",
        "historico": [{"data": "2026-07-22", "producao": 12.0}],
        "del": 239,
        "brinco": "389",
    }
    base.update(overrides)
    return base


def _state(animals: list[dict]) -> str:
    return json.dumps(
        {
            "vacas": animals,
            "insumos": [],
            "usuarios": [
                {"id": "u1", "nome": "Alguém", "email": "a@b.c", "senha": "SEGREDO"}
            ],
            "precoLeite": 2.5,
        },
        ensure_ascii=False,
    )


class TestParseBaseline:
    def test_reads_animal_identity_fields(self) -> None:
        snapshot = parse_baseline(_state([_animal()]))
        animal = snapshot.animals[0]
        assert animal.legacy_id == "v389"
        assert animal.numero_legado == "389"
        assert animal.name == "ÁGATA"
        assert animal.brinco == "389"
        assert animal.brinco_origem == "389"

    def test_normalizes_brinco_and_keeps_raw_value(self) -> None:
        snapshot = parse_baseline(_state([_animal(id="v8", brinco="B2- 008")]))
        animal = snapshot.animals[0]
        assert animal.brinco == "B2-008"
        assert animal.brinco_origem == "B2- 008"

    def test_unreadable_brinco_becomes_none_and_is_recorded(self) -> None:
        snapshot = parse_baseline(
            _state([_animal(id="v-serrana", brinco="B2-XXX", nome="SERRANA")])
        )
        animal = snapshot.animals[0]
        assert animal.brinco is None
        assert animal.brinco_origem == "B2-XXX"
        # O valor ilegível não pode simplesmente desaparecer.
        assert "B2-XXX" in (animal.observacoes or "")

    def test_missing_brinco_is_none_without_observation(self) -> None:
        snapshot = parse_baseline(_state([_animal(id="v204", brinco=None)]))
        animal = snapshot.animals[0]
        assert animal.brinco is None
        assert animal.brinco_origem is None
        assert animal.observacoes is None

    def test_parses_dates_and_leaves_blanks_as_none(self) -> None:
        snapshot = parse_baseline(_state([_animal(parto="2026-01-20", nascimento="")]))
        animal = snapshot.animals[0]
        assert animal.ultimo_parto == date(2026, 1, 20)
        assert animal.nascimento is None

    def test_blank_peso_is_none(self) -> None:
        assert parse_baseline(_state([_animal(peso="")])).animals[0].peso is None

    def test_reads_measurements(self) -> None:
        snapshot = parse_baseline(
            _state(
                [
                    _animal(
                        historico=[
                            {"data": "2026-07-22", "producao": 28.0},
                            {"data": "2026-08-25", "producao": 24.5},
                        ]
                    )
                ]
            )
        )
        animal = snapshot.animals[0]
        assert [m.measured_on for m in animal.measurements] == [
            date(2026, 7, 22),
            date(2026, 8, 25),
        ]
        assert [m.producao for m in animal.measurements] == [28.0, 24.5]

    def test_measurement_carries_observed_lot(self) -> None:
        snapshot = parse_baseline(_state([_animal(lote="LOTE 3")]))
        assert snapshot.animals[0].measurements[0].lote_observado == "LOTE 3"

    def test_does_not_read_users_or_passwords(self) -> None:
        """Nenhuma credencial legada pode atravessar a migração."""
        snapshot = parse_baseline(_state([_animal()]))
        serialized = repr(snapshot)
        assert "senha" not in serialized
        assert "SEGREDO" not in serialized
        assert not hasattr(snapshot, "users")

    def test_computes_source_sha256(self) -> None:
        text = _state([_animal()])
        first = parse_baseline(text)
        second = parse_baseline(text)
        assert first.source_sha256 == second.source_sha256
        assert len(first.source_sha256) == 64
        assert parse_baseline(_state([_animal(nome="OUTRA")])).source_sha256 != (
            first.source_sha256
        )

    def test_counts_reflect_content(self) -> None:
        snapshot = parse_baseline(
            _state(
                [
                    _animal(id="v1", brinco="1"),
                    _animal(id="v2", brinco="2", historico=[]),
                ]
            )
        )
        assert snapshot.animal_count == 2
        assert snapshot.measurement_count == 1


class TestValidateSnapshot:
    def test_rejects_duplicate_legacy_id(self) -> None:
        snapshot = parse_baseline(
            _state([_animal(id="dup", brinco="1"), _animal(id="dup", brinco="2")])
        )
        errors = validate_snapshot(snapshot, expected=None)
        assert any("legacy_id" in e for e in errors)

    def test_rejects_duplicate_brinco(self) -> None:
        snapshot = parse_baseline(
            _state([_animal(id="v1", brinco="777"), _animal(id="v2", brinco="777")])
        )
        errors = validate_snapshot(snapshot, expected=None)
        assert any("brinco" in e for e in errors)

    def test_allows_many_animals_without_brinco(self) -> None:
        snapshot = parse_baseline(
            _state(
                [
                    _animal(id="v1", brinco=None),
                    _animal(id="v2", brinco=None),
                    _animal(id="v3", brinco=None),
                ]
            )
        )
        assert validate_snapshot(snapshot, expected=None) == []

    def test_allows_duplicate_numero_legado(self) -> None:
        snapshot = parse_baseline(
            _state(
                [
                    _animal(id="v346a", numero="346", brinco=None, nome="PONTA FINA"),
                    _animal(
                        id="v346b",
                        numero="346",
                        brinco=None,
                        nome="PONTA FINA DO ABREU",
                    ),
                ]
            )
        )
        assert validate_snapshot(snapshot, expected=None) == []

    def test_rejects_duplicate_measurement_for_same_animal_and_date(self) -> None:
        snapshot = parse_baseline(
            _state(
                [
                    _animal(
                        historico=[
                            {"data": "2026-07-22", "producao": 10.0},
                            {"data": "2026-07-22", "producao": 12.0},
                        ]
                    )
                ]
            )
        )
        errors = validate_snapshot(snapshot, expected=None)
        assert any("2026-07-22" in e for e in errors)

    def test_rejects_empty_legacy_id(self) -> None:
        snapshot = parse_baseline(_state([_animal(id="")]))
        errors = validate_snapshot(snapshot, expected=None)
        assert any("legacy_id" in e for e in errors)

    def test_reports_count_mismatch_against_expected(self) -> None:
        snapshot = parse_baseline(_state([_animal()]))
        errors = validate_snapshot(snapshot, expected=EXPECTED_BASELINE)
        assert any("401" in e for e in errors)
        assert any("152" in e for e in errors)


class TestRealBaseline:
    """Contrato contra o arquivo real do repositório."""

    def test_real_baseline_matches_expected_counts(self, baseline_text: str) -> None:
        snapshot = parse_baseline(baseline_text)
        assert validate_snapshot(snapshot, expected=EXPECTED_BASELINE) == []
        assert snapshot.animal_count == 401
        assert snapshot.measurement_count == 152

    def test_real_baseline_brinco_distribution(self, baseline_text: str) -> None:
        snapshot = parse_baseline(baseline_text)
        with_brinco = [a for a in snapshot.animals if a.brinco]
        assert len(with_brinco) == 259
        assert len({a.brinco for a in with_brinco}) == 259

    def test_real_baseline_measurements_by_date(self, baseline_text: str) -> None:
        snapshot = parse_baseline(baseline_text)
        by_date: dict[date, int] = {}
        for animal in snapshot.animals:
            for measurement in animal.measurements:
                by_date[measurement.measured_on] = (
                    by_date.get(measurement.measured_on, 0) + 1
                )
        assert by_date == {date(2026, 7, 22): 107, date(2026, 8, 25): 45}

    def test_real_baseline_preserves_measurements_of_animals_without_brinco(
        self, baseline_text: str
    ) -> None:
        """As 6 medições de animais sem brinco não podem se perder."""
        snapshot = parse_baseline(baseline_text)
        orphan = [
            m
            for a in snapshot.animals
            if not a.brinco
            for m in a.measurements
        ]
        assert len(orphan) == 8  # 6 sem brinco + 2 de SERRANA (B2-XXX)

    def test_parse_of_real_baseline_is_deterministic(self, baseline_text: str) -> None:
        first = parse_baseline(baseline_text)
        second = parse_baseline(baseline_text)
        assert first == second


class TestValidationRaises:
    def test_validation_error_carries_all_problems(self) -> None:
        with pytest.raises(BaselineValidationError) as excinfo:
            parse_baseline(_state([_animal(id="")])).require_valid(expected=None)
        assert "legacy_id" in str(excinfo.value)
