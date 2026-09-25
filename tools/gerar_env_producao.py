"""Gera os segredos de produção em infra/.env.production.

    python tools/gerar_env_producao.py

- Valores aleatórios fortes (módulo `secrets`), diferentes dos da demonstração.
- Nada é impresso: os valores ficam só no arquivo, que o .gitignore já exclui
  (`.env.*`).
- Não sobrescreve: trocar a senha do banco depois de criado deixaria a API
  sem acesso a ele. Para recomeçar do zero, apague o arquivo e os volumes de
  produção de propósito.
"""

from __future__ import annotations

import secrets
import string
import sys
from pathlib import Path

DESTINO = Path(__file__).resolve().parent.parent / "infra" / ".env.production"

# Só letras e números: vão dentro de uma URL (POSTGRES_URL) e de variáveis
# de ambiente, onde símbolos pediriam escape.
ALFABETO = string.ascii_letters + string.digits


def aleatorio(tamanho: int) -> str:
    return "".join(secrets.choice(ALFABETO) for _ in range(tamanho))


def main() -> int:
    if DESTINO.exists():
        print(f"{DESTINO} já existe; nada foi alterado.")
        return 1

    senha_banco = aleatorio(40)
    conteudo = "\n".join(
        [
            "# Produção deste PC. Gerado por tools/gerar_env_producao.py.",
            "# NÃO versionar, NÃO copiar para conversas. Guarde uma cópia junto",
            "# da senha do backup: sem este arquivo, o banco não abre.",
            "COMPOSE_PROJECT_NAME=belo-vale",
            f"POSTGRES_PASSWORD={senha_banco}",
            f"POSTGRES_URL=postgresql+asyncpg://ingestion:{senha_banco}@db:5432/ingestion",
            f"MINIO_ACCESS_KEY=bv{aleatorio(18)}",
            f"MINIO_SECRET_KEY={aleatorio(48)}",
            f"AUTH_SECRET={aleatorio(64)}",
            "",
        ]
    )
    DESTINO.write_text(conteudo, encoding="utf-8")
    print(f"Criado {DESTINO} com segredos novos (os valores não são exibidos).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
