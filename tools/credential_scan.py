"""Detecta credenciais em texto puro nos arquivos versionados.

A detecção é por *padrão de atribuição* (um campo de senha recebendo um literal),
não por comparação com um valor conhecido: versionar o segredo dentro do gate
recriaria o problema que o gate existe para impedir. Todo valor encontrado é
redigido antes de sair do módulo, para que a saída possa ir a logs e CI.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


#: Valores aceitos num campo de senha: marcadores explicitamente não secretos.
PLACEHOLDER_VALUES = frozenset(
    {
        "LEGADO-SEM-SEGURANCA",
        "REDACTED",
        "CHANGE_ME",
    }
)

#: Valores sintéticos usados em testes. São públicos por natureza (senha
#: deliberadamente errada, usuário de teste criado pelo próprio fluxo, fixture
#: da suíte da API) e nunca corresponderam a uma conta real. Toda entrada aqui
#: é uma exceção explícita e auditável: um valor novo falha o gate por padrão.
SYNTHETIC_TEST_VALUES = frozenset(
    {
        "correct horse battery staple",  # apps/api/tests/test_auth.py, login válido
        "wrong password",  # apps/api/tests/test_auth.py, login inválido
        "errado",  # testes/shot_platform.py, login inválido proposital
        "senha123",  # testes/shot_platform{2,3}.py, usuário de teste do fluxo
        "SEGREDO",  # tests/test_baseline_snapshot.py, prova que o parser não lê senhas
        # tests/test_user_accounts.py: senhas sintéticas do CRUD de contas.
        "bezerra no pasto",  # senha forte de exemplo
        "capim elefante molhado",  # senha forte de exemplo
        "chute errado",  # tentativa inválida, no teste de força bruta
        "senha errada aqui",  # tentativa inválida
        "errada demais",  # senha atual incorreta, na troca de senha
        "123456",  # senha fraca, recusada pela política
    }
)

#: Arquivos que descrevem o próprio gate e por isso contêm exemplos de padrão.
EXEMPT_PATHS = frozenset(
    {
        "tools/credential_scan.py",
        "tools/test_credential_scan.py",
    }
)

#: Extensões varridas. Binários e dependências vendorizadas ficam de fora.
SCANNED_SUFFIXES = frozenset(
    {".json", ".html", ".py", ".md", ".ts", ".tsx", ".yml", ".yaml", ".txt"}
)

_EXCLUDED_PATH_PARTS = ("vendor/", "node_modules/", "package-lock.json")

_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "json-password-field",
        re.compile(r'"(?:senha|password|passwd)"\s*:\s*"([^"]*)"', re.IGNORECASE),
    ),
    (
        "password-fill-literal",
        re.compile(
            r"""fill\(\s*['"][^'"]*(?:loginPass|senha|password)[^'"]*['"]\s*,"""
            r"""\s*['"]([^'"]*)['"]""",
            re.IGNORECASE,
        ),
    ),
    (
        "markdown-inline-password",
        re.compile(r"senha\s*[:=]?\s*`([^`]*)`", re.IGNORECASE),
    ),
)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str
    excerpt: str


def redact(value: str) -> str:
    """Identidade estável de um valor, sem revelá-lo."""
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return f"<redacted len={len(value)} sha256_8={digest}>"


def _is_allowed(value: str) -> bool:
    if not value.strip():
        return True
    return value in PLACEHOLDER_VALUES or value in SYNTHETIC_TEST_VALUES


def scan_text(text: str, *, path: str) -> list[Finding]:
    """Lógica pura: nenhuma leitura de disco, nenhum estado global."""
    findings: list[Finding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for rule, pattern in _RULES:
            for match in pattern.finditer(line):
                value = match.group(1)
                if _is_allowed(value):
                    continue
                findings.append(
                    Finding(
                        path=path,
                        line=line_number,
                        rule=rule,
                        excerpt=redact(value),
                    )
                )
    return findings


def should_scan(path: str) -> bool:
    if path in EXEMPT_PATHS:
        return False
    if any(part in path for part in _EXCLUDED_PATH_PARTS):
        return False
    return Path(path).suffix.lower() in SCANNED_SUFFIXES


def scan_repository(root: Path, paths: Iterable[str]) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        if not should_scan(path):
            continue
        absolute = root / path
        try:
            text = absolute.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        findings.extend(scan_text(text, path=path))
    return findings


def main(argv: Sequence[str] | None = None) -> int:
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    tracked = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True
    ).stdout
    paths = [
        name.decode("utf-8", "surrogateescape") for name in tracked.split(b"\0") if name
    ]
    findings = scan_repository(root, paths)
    for finding in findings:
        print(
            f"{finding.path}:{finding.line} [{finding.rule}] {finding.excerpt}",
            file=sys.stderr,
        )
    print(f"findings={len(findings)}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
