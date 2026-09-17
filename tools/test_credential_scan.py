"""Gate: nenhuma credencial em texto puro deve existir no HEAD.

O scanner detecta *padrões de atribuição* de credencial, nunca compara com um
valor conhecido -- se comparasse, o próprio teste teria de versionar o segredo.
"""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

from credential_scan import (
    PLACEHOLDER_VALUES,
    SYNTHETIC_TEST_VALUES,
    Finding,
    redact,
    scan_repository,
    scan_text,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class ScanTextTests(unittest.TestCase):
    def test_flags_json_password_field(self) -> None:
        findings = scan_text('  "senha": "VerdadeiraSenha1",', path="state.json")
        self.assertEqual([f.rule for f in findings], ["json-password-field"])
        self.assertEqual(findings[0].line, 1)

    def test_accepts_documented_placeholder(self) -> None:
        for placeholder in PLACEHOLDER_VALUES:
            with self.subTest(placeholder=placeholder):
                self.assertEqual(
                    scan_text(f'"senha": "{placeholder}"', path="state.json"), []
                )

    def test_accepts_declared_synthetic_test_values(self) -> None:
        for value in SYNTHETIC_TEST_VALUES:
            with self.subTest(value=value):
                self.assertEqual(
                    scan_text(f'"senha": "{value}"', path="t.py"), []
                )

    def test_rejects_value_not_declared_as_synthetic(self) -> None:
        self.assertTrue(scan_text('"senha": "NaoDeclarada"', path="t.py"))

    def test_accepts_empty_password_field(self) -> None:
        self.assertEqual(scan_text('"senha": ""', path="state.json"), [])

    def test_flags_playwright_password_fill(self) -> None:
        findings = scan_text(
            "await page.fill('#loginPass', 'SenhaDeVerdade')", path="t.py"
        )
        self.assertEqual([f.rule for f in findings], ["password-fill-literal"])

    def test_flags_markdown_inline_password(self) -> None:
        findings = scan_text("senha `SenhaDeVerdade` (Administrador).", path="README.md")
        self.assertEqual([f.rule for f in findings], ["markdown-inline-password"])

    def test_reports_every_offending_line(self) -> None:
        findings = scan_text(
            '"senha": "UmaSenha"\n"nome": "Fulano"\n"senha": "OutraSenha"\n',
            path="state.json",
        )
        self.assertEqual([f.line for f in findings], [1, 3])

    def test_finding_never_carries_the_raw_secret(self) -> None:
        secret = "SenhaSuperSecreta42"
        findings = scan_text(f'"senha": "{secret}"', path="state.json")
        self.assertTrue(findings)
        for finding in findings:
            self.assertNotIn(secret, repr(finding))
            self.assertNotIn(secret, finding.excerpt)

    def test_redact_is_stable_and_reveals_no_value(self) -> None:
        self.assertEqual(redact("abc"), redact("abc"))
        self.assertNotEqual(redact("abc"), redact("abd"))
        self.assertNotIn("abc", redact("abc"))


class RepositoryScanTests(unittest.TestCase):
    def test_head_has_no_plaintext_credentials(self) -> None:
        tracked = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            check=True,
        ).stdout
        paths = [
            name.decode("utf-8", "surrogateescape")
            for name in tracked.split(b"\0")
            if name
        ]
        findings: list[Finding] = scan_repository(REPOSITORY_ROOT, paths)
        self.assertEqual(
            findings,
            [],
            "credenciais em texto puro encontradas (valores redigidos):\n"
            + "\n".join(f"  {f.path}:{f.line} [{f.rule}] {f.excerpt}" for f in findings),
        )


if __name__ == "__main__":
    unittest.main()
