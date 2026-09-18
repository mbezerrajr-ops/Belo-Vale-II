"""Política de senha.

A aplicação fica exposta na internet pública e é usada por pessoas não
técnicas — dono da fazenda e funcionários. A política foi desenhada para
barrar o que de fato é quebrado na prática (senha curta, óbvia, ou derivada do
próprio e-mail) sem exigir combinações de símbolos que levam as pessoas a
anotar a senha num papel colado no monitor.

Comprimento vence complexidade: uma frase como "capim elefante molhado" é mais
difícil de quebrar e mais fácil de lembrar do que "S3nh@!23".
"""

from __future__ import annotations

import re
import unicodedata


#: Comprimento mínimo. Alto o bastante para inviabilizar força bruta mesmo sem
#: exigir símbolos, e alcançável com duas ou três palavras comuns.
MINIMUM_LENGTH = 12

#: Termos que não podem aparecer como a senha inteira nem dominá-la. São os
#: primeiros palpites de qualquer ataque contra este sistema.
_FORBIDDEN_TERMS = frozenset(
    {
        "senha",
        "password",
        "belovale",
        "belovaleii",
        "fazenda",
        "123456",
        "qwerty",
        "admin",
        "leite",
        "vaca",
    }
)

_DIGITS_ONLY = re.compile(r"^\d+$")
_LETTERS_ONLY_ONE = re.compile(r"^(.)\1+$")


class PasswordPolicyError(ValueError):
    """Senha recusada. A mensagem é escrita para o usuário final e nunca
    contém a senha."""


def _fold(value: str) -> str:
    """Minúsculas, sem acento e sem espaços, para comparar de forma robusta."""
    decomposed = unicodedata.normalize("NFKD", value.lower())
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[\s._-]+", "", stripped)


def describe_policy() -> str:
    return (
        f"A senha precisa ter pelo menos {MINIMUM_LENGTH} caracteres. "
        "Prefira uma frase fácil de lembrar, como três palavras juntas. "
        "Não use apenas números, palavras óbvias nem partes do seu e-mail."
    )


def validate_password(password: str, *, email: str | None = None) -> None:
    """Levanta :class:`PasswordPolicyError` se a senha for recusada."""
    if len(password) < MINIMUM_LENGTH:
        raise PasswordPolicyError(
            f"A senha precisa ter pelo menos {MINIMUM_LENGTH} caracteres. "
            "Uma frase com três palavras costuma ser fácil de lembrar e segura."
        )

    if _DIGITS_ONLY.match(password):
        raise PasswordPolicyError(
            "A senha não pode ser formada apenas por números. "
            "Misture palavras para ficar mais difícil de adivinhar."
        )

    if _LETTERS_ONLY_ONE.match(password):
        raise PasswordPolicyError(
            "A senha não pode repetir sempre o mesmo caractere."
        )

    folded = _fold(password)

    for term in _FORBIDDEN_TERMS:
        if term in folded:
            raise PasswordPolicyError(
                "A senha contém uma palavra fácil de adivinhar. "
                "Escolha algo que não tenha relação com o sistema ou a fazenda."
            )

    if email:
        local_part = _fold(email.split("@", 1)[0])
        # Trechos muito curtos apareceriam em quase qualquer senha; exigir um
        # mínimo evita recusar senhas boas por coincidência de duas letras.
        if len(local_part) >= 4 and local_part in folded:
            raise PasswordPolicyError(
                "A senha não pode conter parte do seu e-mail. "
                "Escolha palavras sem relação com seu nome de usuário."
            )
