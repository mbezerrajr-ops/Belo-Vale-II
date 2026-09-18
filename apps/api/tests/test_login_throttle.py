"""Proteção do login contra força bruta.

Exposta na internet pública, a tela de login é varrida por bots. Sem limite de
tentativas, a senha de um funcionário é adivinhável por repetição.

O limite é por conta **e** por origem: limitar só por conta permitiria varrer
muitas contas de um mesmo IP, e limitar só por IP puniria a fazenda inteira
quando todos saem pelo mesmo endereço.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.login_throttle import (
    LOCKOUT_SECONDS,
    MAX_ATTEMPTS,
    LoginThrottle,
)


def _at(seconds: int) -> datetime:
    return datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc) + timedelta(
        seconds=seconds
    )


@pytest.fixture()
def throttle() -> LoginThrottle:
    return LoginThrottle()


class TestFailureCounting:
    def test_allows_attempts_below_the_limit(self, throttle) -> None:
        for index in range(MAX_ATTEMPTS - 1):
            assert throttle.check("joao@belovale", "10.0.0.1", now=_at(index)) is None
            throttle.record_failure("joao@belovale", "10.0.0.1", now=_at(index))

        assert throttle.check("joao@belovale", "10.0.0.1", now=_at(99)) is None

    def test_blocks_after_reaching_the_limit(self, throttle) -> None:
        for index in range(MAX_ATTEMPTS):
            throttle.record_failure("joao@belovale", "10.0.0.1", now=_at(index))

        retry_after = throttle.check("joao@belovale", "10.0.0.1", now=_at(MAX_ATTEMPTS))
        assert retry_after is not None
        assert retry_after > 0

    def test_success_clears_the_counter(self, throttle) -> None:
        for index in range(MAX_ATTEMPTS - 1):
            throttle.record_failure("joao@belovale", "10.0.0.1", now=_at(index))
        throttle.record_success("joao@belovale", "10.0.0.1")

        assert throttle.check("joao@belovale", "10.0.0.1", now=_at(50)) is None

    def test_lockout_expires(self, throttle) -> None:
        for index in range(MAX_ATTEMPTS):
            throttle.record_failure("joao@belovale", "10.0.0.1", now=_at(index))

        assert throttle.check("joao@belovale", "10.0.0.1", now=_at(1)) is not None
        assert (
            throttle.check(
                "joao@belovale", "10.0.0.1", now=_at(LOCKOUT_SECONDS + 60)
            )
            is None
        )


class TestScoping:
    def test_blocking_one_account_does_not_block_another(self, throttle) -> None:
        for index in range(MAX_ATTEMPTS):
            throttle.record_failure("joao@belovale", "10.0.0.1", now=_at(index))

        assert throttle.check("maria@belovale", "10.0.0.2", now=_at(10)) is None

    def test_same_account_from_another_origin_is_also_blocked(self, throttle) -> None:
        """Trocar de IP não pode zerar o bloqueio de uma conta sob ataque."""
        for index in range(MAX_ATTEMPTS):
            throttle.record_failure("joao@belovale", "10.0.0.1", now=_at(index))

        assert throttle.check("joao@belovale", "203.0.113.9", now=_at(10)) is not None

    def test_one_origin_attacking_many_accounts_is_blocked(self, throttle) -> None:
        """Varrer muitas contas de um mesmo IP também é força bruta."""
        for index in range(MAX_ATTEMPTS):
            throttle.record_failure(f"conta{index}@belovale", "203.0.113.9", now=_at(index))

        assert throttle.check("outra@belovale", "203.0.113.9", now=_at(50)) is not None

    def test_email_comparison_ignores_case(self, throttle) -> None:
        for index in range(MAX_ATTEMPTS):
            throttle.record_failure("Joao@BeloVale", "10.0.0.1", now=_at(index))

        assert throttle.check("joao@belovale", "10.0.0.1", now=_at(10)) is not None


class TestMemoryHygiene:
    def test_old_entries_do_not_accumulate_forever(self, throttle) -> None:
        for index in range(50):
            throttle.record_failure(f"bot{index}@x", f"10.0.0.{index}", now=_at(index))

        throttle.check("alguem@belovale", "10.0.0.250", now=_at(LOCKOUT_SECONDS * 10))

        assert throttle.tracked_keys() < 50
