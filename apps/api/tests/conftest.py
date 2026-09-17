from pathlib import Path

import pytest


#: `apps/api/tests/conftest.py` → raiz do repositório.
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

CANONICAL_STATE = (
    REPOSITORY_ROOT
    / "belo-vale-ii-projeto-completo"
    / "plataforma"
    / "state_canonical.json"
)


@pytest.fixture(scope="session")
def baseline_path() -> Path:
    if not CANONICAL_STATE.exists():
        pytest.skip(f"estado canônico não encontrado em {CANONICAL_STATE}")
    return CANONICAL_STATE


@pytest.fixture(scope="session")
def baseline_text(baseline_path: Path) -> str:
    return baseline_path.read_text(encoding="utf-8")
