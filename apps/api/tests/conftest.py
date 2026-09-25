from pathlib import Path

import pytest


def _canonical_state() -> Path | None:
    """O estado canônico da base antiga, subindo a partir desta pasta.

    No repositório, os testes ficam em `apps/api/tests`. Na imagem de teste
    do compose, em `/app/tests`, sem a pasta do legado: ali não há três
    níveis acima (o `parents[3]` fixo quebrava a coleta inteira), e os testes
    da base antiga são pulados."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "belo-vale-ii-projeto-completo" / "plataforma" / "state_canonical.json"
        if candidate.is_file():
            return candidate
    return None


CANONICAL_STATE = _canonical_state()


@pytest.fixture(scope="session")
def baseline_path() -> Path:
    if CANONICAL_STATE is None:
        pytest.skip("estado canônico da base antiga não encontrado acima de tests/")
    return CANONICAL_STATE


@pytest.fixture(scope="session")
def baseline_text(baseline_path: Path) -> str:
    return baseline_path.read_text(encoding="utf-8")
