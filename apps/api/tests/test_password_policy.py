"""Política de senha.

A aplicação fica exposta na internet pública e será usada por pessoas não
técnicas. A política precisa barrar o que realmente é quebrado na prática —
senha curta, óbvia ou ligada ao próprio usuário — sem exigir ginástica de
símbolos que leva todo mundo a anotar a senha num papel.
"""

import pytest

from app.core.password_policy import (
    MINIMUM_LENGTH,
    PasswordPolicyError,
    describe_policy,
    validate_password,
)


class TestLength:
    def test_accepts_a_long_passphrase(self) -> None:
        validate_password("capim elefante molhado")

    def test_rejects_shorter_than_minimum(self) -> None:
        with pytest.raises(PasswordPolicyError) as excinfo:
            validate_password("a" * (MINIMUM_LENGTH - 1))
        assert str(MINIMUM_LENGTH) in str(excinfo.value)

    def test_accepts_exactly_the_minimum(self) -> None:
        validate_password("pasto" + "z" * (MINIMUM_LENGTH - 5))

    def test_rejects_empty(self) -> None:
        with pytest.raises(PasswordPolicyError):
            validate_password("")


class TestObviousPasswords:
    def test_rejects_common_passwords(self) -> None:
        for weak in ("senha123456789", "123456789012", "password1234"):
            with pytest.raises(PasswordPolicyError), pytest.MonkeyPatch().context():
                validate_password(weak)

    def test_rejects_only_digits(self) -> None:
        with pytest.raises(PasswordPolicyError) as excinfo:
            validate_password("1234567890123")
        assert "números" in str(excinfo.value).lower()

    def test_rejects_a_single_repeated_character(self) -> None:
        with pytest.raises(PasswordPolicyError):
            validate_password("aaaaaaaaaaaaaa")

    def test_rejects_the_farm_name(self) -> None:
        with pytest.raises(PasswordPolicyError):
            validate_password("belovale2026belovale")


class TestRelatedToTheUser:
    def test_rejects_password_containing_the_email_local_part(self) -> None:
        with pytest.raises(PasswordPolicyError) as excinfo:
            validate_password("joaosilva no pasto", email="joaosilva@fazenda.com")
        assert "e-mail" in str(excinfo.value).lower()

    def test_comparison_ignores_case(self) -> None:
        with pytest.raises(PasswordPolicyError):
            validate_password("JOAOSILVA no pasto", email="joaosilva@fazenda.com")

    def test_accepts_when_unrelated_to_the_email(self) -> None:
        validate_password("capim elefante molhado", email="joaosilva@fazenda.com")

    def test_short_email_local_part_does_not_block_everything(self) -> None:
        """Um e-mail curto como `jo@x.com` não pode invalidar toda senha que
        contenha essas duas letras."""
        validate_password("bezerra no pasto", email="jo@fazenda.com")


class TestPolicyDescription:
    def test_describes_the_rules_for_the_user_interface(self) -> None:
        described = describe_policy()
        assert str(MINIMUM_LENGTH) in described
        assert described.strip()

    def test_error_message_is_actionable_and_in_portuguese(self) -> None:
        with pytest.raises(PasswordPolicyError) as excinfo:
            validate_password("curta")
        message = str(excinfo.value)
        assert "senha" in message.lower()
        # Mensagem para pessoa leiga, não para desenvolvedor.
        assert "must" not in message.lower()


class TestNoLeak:
    def test_error_never_contains_the_password(self) -> None:
        secret = "aaaaaaaaaaaaaaaa"
        try:
            validate_password(secret)
        except PasswordPolicyError as error:
            assert secret not in str(error)
        else:  # pragma: no cover
            pytest.fail("senha fraca deveria ter sido recusada")
