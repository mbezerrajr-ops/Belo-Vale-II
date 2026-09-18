"""Senha provisória para redefinição feita pelo administrador.

Três palavras e dois dígitos, como ``caju-pedra-rio-47``: fácil de ditar por
telefone para um funcionário e de digitar no celular, sem letras ambíguas.
São cerca de 26 bits, o que basta para uma senha que expira em
``TEMPORARY_PASSWORD_TTL``, só serve para escolher outra e está atrás do
limite de tentativas de login.

As palavras não têm acento (digitação) e nenhuma contém termo proibido pela
política de senha (``vaca``, ``leite``, ``fazenda``…); o gerador ainda assim
valida o resultado, para que uma lista editada no futuro não produza uma
senha que a própria política recusaria.
"""

from __future__ import annotations

import secrets
from datetime import timedelta

from app.core.password_policy import PasswordPolicyError, validate_password

#: Validade da senha provisória. Três dias cobrem um fim de semana sem
#: deixar uma senha repassada por mensagem valendo indefinidamente.
TEMPORARY_PASSWORD_TTL = timedelta(hours=72)

_WORDS = (
    "abelha", "acude", "agua", "alecrim", "algodao", "amora", "angico", "areia",
    "arroz", "aroeira", "baiao", "balde", "barro", "batata", "beija", "bode",
    "brisa", "buriti", "cabra", "cacau", "caju", "cancela", "capim", "carcara",
    "cerca", "chuva", "cipo", "coco", "corda", "cuscuz", "estrada", "facho",
    "farol", "feijao", "figo", "flor", "fogo", "fole", "folha", "galo",
    "goiaba", "grama", "graviola", "ingazeira", "ipe", "jaca", "jambo", "jegue",
    "juazeiro", "lagoa", "lima", "lua", "macaxeira", "mandacaru", "manga",
    "maracuja", "mel", "milho", "morro", "mulungu", "nuvem", "oiti", "onda",
    "palha", "pedra", "pequi", "pilao", "pinha", "pitanga", "pitomba", "poco",
    "porteira", "quiabo", "rede", "riacho", "rio", "roca", "sabia", "sal",
    "sanfona", "seriema", "serra", "sertao", "sol", "tapioca", "tatu", "trilha",
    "tucum", "umbu", "urucum", "vento", "xique", "zabumba",
)


def generate_temporary_password() -> str:
    while True:
        words = [secrets.choice(_WORDS) for _ in range(3)]
        candidate = "-".join([*words, f"{secrets.randbelow(100):02d}"])
        try:
            validate_password(candidate)
        except PasswordPolicyError:
            continue
        return candidate
