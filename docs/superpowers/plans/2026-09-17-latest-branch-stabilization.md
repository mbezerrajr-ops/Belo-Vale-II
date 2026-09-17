# Latest Branch Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Estabilizar a branch mais recente como baseline completa e reproduzível, preservando 401 animais e 152 medições enquanto elimina IDs técnicos duplicados.

**Architecture:** Um módulo Python sem dependências externas define o contrato, validação e transformação do estado. Uma CLI fina extrai o estado legado, valida, gera o JSON canônico e reconstrói os artefatos derivados; o importador de PDF passa a consumir essas interfaces. Decisões zootécnicas incertas continuam como avisos explícitos, nunca como mutações automáticas.

**Tech Stack:** Python 3.13 (`unittest`, `json`, `argparse`, `pathlib`), HTML/JavaScript legado, pdfplumber, Playwright já versionado em `apps/web`.

**Spec:** `docs/superpowers/specs/2026-09-17-latest-branch-stabilization-design.md`

## Global Constraints

- A baseline é o commit `c3854c26b8697050a118d10123103b4b7d31d763`.
- Preservar exatamente 401 animais e 152 medições.
- Preservar 107 medições em `2026-07-22` e 45 em `2026-08-25`.
- Não excluir nem fundir animais automaticamente.
- Não alterar situação com base apenas em lote ou DEL.
- Todo comportamento novo ou corrigido segue RED → GREEN → REFACTOR.
- Funções de domínio não leem arquivos, não escrevem arquivos e não dependem de pdfplumber.
- Comandos de escrita validam o estado completo antes de substituir artefatos.
- A futura migração PostgreSQL fica fora desta fase.

---

### Task 1: Contrato executável do estado legado

**Files:**
- Create: `belo-vale-ii-projeto-completo/plataforma/state_contract.py`
- Create: `belo-vale-ii-projeto-completo/testes/test_state_contract.py`

**Interfaces:**
- Produces: `extract_state_from_html(html: str) -> dict[str, Any]`.
- Produces: `inject_state_into_html(template: str, state: Mapping[str, Any]) -> str`.
- Produces: `summarize_state(state: Mapping[str, Any]) -> StateSummary`.
- Produces: `validate_state(state: Mapping[str, Any], expected: StateSummary | None = None) -> ValidationReport`.
- Produces immutable `StateSummary` and `ValidationReport` dataclasses.

- [ ] **Step 1: Write the failing extraction and baseline tests**

Create `test_state_contract.py` with path resolution relative to the test file, not the current working directory:

```python
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLATFORM = ROOT / "plataforma"
sys.path.insert(0, str(PLATFORM))

from state_contract import extract_state_from_html, summarize_state, validate_state


class BaselineStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        html = (PLATFORM / "platform_ATUAL_publicado.html").read_text(encoding="utf-8")
        cls.state = extract_state_from_html(html)

    def test_baseline_counts_are_preserved(self) -> None:
        summary = summarize_state(self.state)
        self.assertEqual(summary.animal_count, 401)
        self.assertEqual(summary.measurement_count, 152)
        self.assertEqual(summary.measurements_by_date, {
            "2026-07-22": 107,
            "2026-08-25": 45,
        })
        self.assertEqual(summary.supply_count, 4)
        self.assertEqual(summary.user_count, 2)

    def test_baseline_reports_duplicate_or_empty_ids(self) -> None:
        report = validate_state(self.state)
        self.assertEqual(report.duplicate_ids, ("v", "v346", "v570"))
        self.assertIn("animal_ids_not_unique", report.errors)

    def test_baseline_reports_del_situation_warnings_without_mutating(self) -> None:
        report = validate_state(self.state)
        self.assertEqual(report.del_situation_warning_count, 30)
        self.assertEqual(self.state["vacas"][0]["nome"], "ÁGATA")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify RED**

Run:

```powershell
python -m unittest belo-vale-ii-projeto-completo/testes/test_state_contract.py -v
```

Expected: ERROR with `ModuleNotFoundError: No module named 'state_contract'`.

- [ ] **Step 3: Implement the minimal pure contract**

Create `state_contract.py` with:

```python
from __future__ import annotations

import copy
import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping

STATE_PATTERN = re.compile(
    r'<script id="state-data" type="application/json">([\s\S]*?)</script>'
)


@dataclass(frozen=True)
class StateSummary:
    animal_count: int
    measurement_count: int
    measurements_by_date: dict[str, int]
    supply_count: int
    user_count: int


@dataclass(frozen=True)
class ValidationReport:
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    duplicate_ids: tuple[str, ...]
    del_situation_warning_count: int


def extract_state_from_html(html: str) -> dict[str, Any]:
    match = STATE_PATTERN.search(html)
    if match is None:
        raise ValueError("state-data block not found")
    value = json.loads(match.group(1))
    if not isinstance(value, dict):
        raise ValueError("state-data must contain a JSON object")
    return value


def inject_state_into_html(template: str, state: Mapping[str, Any]) -> str:
    encoded = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
    replacement = f'<script id="state-data" type="application/json">{encoded}</script>'
    if "__STATE_JSON__" in template:
        return template.replace("__STATE_JSON__", encoded, 1)
    rendered, count = STATE_PATTERN.subn(replacement, template, count=1)
    if count != 1:
        raise ValueError("state-data block not found")
    return rendered


def summarize_state(state: Mapping[str, Any]) -> StateSummary:
    animals = list(state.get("vacas", []))
    dates = Counter(
        entry["data"]
        for animal in animals
        for entry in animal.get("historico", [])
    )
    return StateSummary(
        animal_count=len(animals),
        measurement_count=sum(dates.values()),
        measurements_by_date=dict(sorted(dates.items())),
        supply_count=len(state.get("insumos", [])),
        user_count=len(state.get("usuarios", [])),
    )


def validate_state(
    state: Mapping[str, Any], expected: StateSummary | None = None
) -> ValidationReport:
    animals = list(state.get("vacas", []))
    ids = [str(animal.get("id", "")).strip() for animal in animals]
    duplicates = tuple(sorted(key for key, count in Counter(ids).items() if count > 1))
    errors: list[str] = []
    if "" in ids:
        errors.append("animal_id_empty")
    if duplicates:
        errors.append("animal_ids_not_unique")
    summary = summarize_state(state)
    if expected is not None and summary != expected:
        errors.append("baseline_summary_changed")
    warnings = [
        animal
        for animal in animals
        if "brinco" in animal
        and str(animal.get("del", "")) == ""
        and animal.get("situacao") == "Em lactação"
    ]
    warning_codes = ("del_empty_while_lactating",) if warnings else ()
    return ValidationReport(
        errors=tuple(errors),
        warnings=warning_codes,
        duplicate_ids=duplicates,
        del_situation_warning_count=len(warnings),
    )
```

- [ ] **Step 4: Run the contract tests to verify GREEN**

Run the same `unittest` command.

Expected: 3 tests PASS, including the characterization that the unmodified baseline contains three duplicate ID groups.

- [ ] **Step 5: Commit the executable contract**

```powershell
git add belo-vale-ii-projeto-completo/plataforma/state_contract.py belo-vale-ii-projeto-completo/testes/test_state_contract.py
git commit -m "test(plataforma): codify latest state baseline"
```

### Task 2: Reparo determinístico e idempotente de IDs

**Files:**
- Modify: `belo-vale-ii-projeto-completo/plataforma/state_contract.py`
- Modify: `belo-vale-ii-projeto-completo/testes/test_state_contract.py`

**Interfaces:**
- Consumes: `validate_state` from Task 1.
- Produces: `repair_animal_ids(state: Mapping[str, Any]) -> dict[str, Any]`.
- Guarantee: returns a deep copy; only `vacas[*].id` may change.

- [ ] **Step 1: Add failing pure tests for preservation and idempotence**

Add tests that:

```python
from copy import deepcopy
from state_contract import repair_animal_ids

def without_ids(state):
    result = deepcopy(state)
    for animal in result["vacas"]:
        animal.pop("id", None)
    return result


class AnimalIdRepairTests(unittest.TestCase):
    def test_repair_changes_only_duplicate_ids(self) -> None:
        original = deepcopy(BaselineStateTests.state)
        repaired = repair_animal_ids(original)
        self.assertEqual(without_ids(repaired), without_ids(original))
        self.assertEqual(validate_state(repaired).duplicate_ids, ())
        self.assertNotIn("animal_ids_not_unique", validate_state(repaired).errors)

    def test_repair_is_idempotent(self) -> None:
        once = repair_animal_ids(BaselineStateTests.state)
        twice = repair_animal_ids(once)
        self.assertEqual(twice, once)

    def test_repair_keeps_all_six_colliding_records(self) -> None:
        repaired = repair_animal_ids(BaselineStateTests.state)
        names = [
            animal["nome"] for animal in repaired["vacas"]
            if animal["nome"] in {
                "CAMBRAIA", "MIMOSA", "PONTA FINA",
                "PONTA FINA DO ABREU", "MALHADINHA", "SERRANA",
            }
        ]
        self.assertCountEqual(names, [
            "CAMBRAIA", "MIMOSA", "PONTA FINA",
            "PONTA FINA DO ABREU", "MALHADINHA", "SERRANA",
        ])
```

- [ ] **Step 2: Run the pure tests to verify RED**

Expected: import failure because `repair_animal_ids` does not exist.

- [ ] **Step 3: Implement deterministic ID repair**

Add a private ASCII slug helper using `unicodedata.normalize`, derive candidates only for duplicated/empty IDs from old ID + brinco/numero + name, sort a collision group by `(brinco, numero, nome)`, and append `-2`, `-3` only if the derived candidate still collides. Preserve every already unique non-empty ID exactly.

`repair_animal_ids` must start with `copy.deepcopy(state)` and return the copy.

- [ ] **Step 4: Run pure tests to verify GREEN**

Expected: all state-contract tests PASS.

- [ ] **Step 5: Commit the ID repair with a green suite**

```powershell
git add belo-vale-ii-projeto-completo/plataforma/state_contract.py belo-vale-ii-projeto-completo/testes/test_state_contract.py
git commit -m "fix(plataforma): derive stable unique animal ids"
```

### Task 3: Estado canônico e geração reproduzível

**Files:**
- Create: `belo-vale-ii-projeto-completo/plataforma/build_platform_state.py`
- Create: `belo-vale-ii-projeto-completo/plataforma/state_canonical.json`
- Modify: `belo-vale-ii-projeto-completo/plataforma/platform_ATUAL_publicado.html`
- Modify: `belo-vale-ii-projeto-completo/plataforma/state_dados_atuais.json`
- Modify: `belo-vale-ii-projeto-completo/testes/test_state_contract.py`
- Create: `apps/web/e2e/legacy-platform.spec.ts`

**Interfaces:**
- Consumes: extraction, validation, summary and ID repair from Tasks 1–2.
- Produces CLI commands `bootstrap`, `validate`, and `generate`.
- Produces canonical JSON and deterministic derived files.

- [ ] **Step 1: Add the failing UI regression test before changing real data**

Create `legacy-platform.spec.ts`. Resolve the HTML with `path.resolve`, read credentials from its `state-data`, install a minimal `window.claude` fake with `page.addInitScript`, log in, open the Vacas tab, locate the MIMOSA row, change its lot and assert that MIMOSA — not CAMBRAIA — changed after re-render.

The key assertion must be observable UI behavior:

```typescript
const mimosa = page.getByRole("row").filter({ hasText: "MIMOSA" });
const cambraia = page.getByRole("row").filter({ hasText: "CAMBRAIA" });
await mimosa.locator("select.lotesel").selectOption("LOTE 3");
await expect(mimosa.locator("select.lotesel")).toHaveValue("LOTE 3");
await expect(cambraia.locator("select.lotesel")).not.toHaveValue("LOTE 3");
```

- [ ] **Step 2: Run the UI test to verify RED**

Run:

```powershell
Set-Location apps/web
npm ci
npx playwright install chromium
npx playwright test e2e/legacy-platform.spec.ts
```

Expected: FAIL because both records use `v570` and the event updates the first match.

- [ ] **Step 3: Add failing round-trip and projection tests**

Tests must use `tempfile.TemporaryDirectory` and assert:

```python
def test_template_round_trip_preserves_logical_state(self) -> None:
    template = (PLATFORM / "platform_ATUAL_template.html").read_text(encoding="utf-8")
    rendered = inject_state_into_html(template, self.state)
    self.assertEqual(extract_state_from_html(rendered), self.state)

def test_projection_removes_only_animal_history(self) -> None:
    projected = project_state_without_history(self.state)
    self.assertEqual(len(projected["vacas"]), 401)
    self.assertTrue(all("historico" not in animal for animal in projected["vacas"]))
    restored = deepcopy(projected)
    for source, target in zip(self.state["vacas"], restored["vacas"], strict=True):
        target["historico"] = source.get("historico", [])
    self.assertEqual(restored, self.state)
```

- [ ] **Step 4: Run tests to verify RED**

Expected: import failure for `project_state_without_history`.

- [ ] **Step 5: Implement projection and atomic file helpers**

Add `project_state_without_history`. In the CLI, write to a sibling temporary file using `tempfile.NamedTemporaryFile(delete=False, dir=target.parent)`, flush, then replace the target with `Path.replace` only after validation succeeds.

Commands:

```text
bootstrap --published platform_ATUAL_publicado.html --canonical state_canonical.json
validate --canonical state_canonical.json
generate --canonical state_canonical.json --template platform_ATUAL_template.html \
         --published platform_ATUAL_publicado.html --projection state_dados_atuais.json
```

`bootstrap` extracts the current HTML, repairs IDs, validates against the fixed baseline summary, and writes only the canonical JSON. `generate` validates again before writing both derivatives.

- [ ] **Step 6: Run tests to verify GREEN**

Expected: all state-contract tests PASS.

- [ ] **Step 7: Bootstrap and regenerate the real artifacts**

Run from `plataforma/`:

```powershell
python build_platform_state.py bootstrap --published platform_ATUAL_publicado.html --canonical state_canonical.json
python build_platform_state.py validate --canonical state_canonical.json
python build_platform_state.py generate --canonical state_canonical.json --template platform_ATUAL_template.html --published platform_ATUAL_publicado.html --projection state_dados_atuais.json
```

Expected summary: 401 animals, 152 measurements, no structural errors, 30 business warnings.

- [ ] **Step 8: Run pure tests and the UI regression**

Run `unittest`, then the specific Playwright spec from Task 3.

Expected: both PASS. The E2E proves the MIMOSA edit no longer targets CAMBRAIA.

- [ ] **Step 9: Commit the canonical source and generated artifacts**

```powershell
git add belo-vale-ii-projeto-completo/plataforma/build_platform_state.py belo-vale-ii-projeto-completo/plataforma/state_canonical.json belo-vale-ii-projeto-completo/plataforma/platform_ATUAL_publicado.html belo-vale-ii-projeto-completo/plataforma/state_dados_atuais.json belo-vale-ii-projeto-completo/testes/test_state_contract.py apps/web/e2e/legacy-platform.spec.ts
git commit -m "feat(plataforma): establish canonical latest state"
```

### Task 4: Importador modular e idempotente

**Files:**
- Modify: `belo-vale-ii-projeto-completo/plataforma/import_relatorio_animais.py`
- Create: `belo-vale-ii-projeto-completo/plataforma/requirements-import.txt`
- Create: `belo-vale-ii-projeto-completo/testes/test_import_relatorio_animais.py`

**Interfaces:**
- Produces: `read_pdf_rows(path: Path) -> list[dict[str, str]]`.
- Produces: `match_report_rows(state, rows) -> MatchResult`.
- Produces: `apply_report_rows(state, rows) -> ImportResult`.
- Produces: `render_import_report(result: ImportResult) -> str`.
- Consumes canonical I/O from Tasks 1–3.

- [ ] **Step 1: Write a failing test proving module import does not require pdfplumber**

The test imports `import_relatorio_animais` without invoking PDF reading and asserts that `apply_report_rows` exists. It must fail against the current script because importing executes `ler_pdf()` and imports unavailable `pdfplumber` globally.

- [ ] **Step 2: Run the test to verify RED**

Run:

```powershell
python -m unittest belo-vale-ii-projeto-completo/testes/test_import_relatorio_animais.py -v
```

Expected: ERROR from missing `pdfplumber` or top-level execution.

- [ ] **Step 3: Refactor only enough to make import safe**

Move `import pdfplumber` inside `read_pdf_rows`, move all execution into `main(argv: list[str] | None = None) -> int`, and add the standard guard:

```python
if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Add failing idempotence and preservation tests**

Use a small literal state containing an existing animal with two history entries and literal report rows containing one match plus one new animal. Assert that applying the same rows twice:

- retains two animals rather than three;
- preserves the existing history exactly;
- produces the same IDs on both runs;
- reports the second execution as zero new animals.

- [ ] **Step 5: Run tests to verify RED**

Expected: FAIL because `apply_report_rows` is absent or not idempotent.

- [ ] **Step 6: Extract matching and application into pure functions**

Move the existing matching passes without changing their order or business rules. Accept rows and state as parameters. Use `repair_animal_ids` after application. Return immutable summary/result objects instead of writing logs inside the domain function.

- [ ] **Step 7: Run tests to verify GREEN**

Expected: importer and state-contract suites PASS without pdfplumber installed.

- [ ] **Step 8: Declare and install the PDF dependency**

Create:

```text
pdfplumber>=0.11,<1.0
```

Install with:

```powershell
python -m pip install -r belo-vale-ii-projeto-completo/plataforma/requirements-import.txt
```

- [ ] **Step 9: Add and run a real-PDF dry-run test**

Read `docs/RELÁTORIO DE TODOS ANIMAIS.pdf`, assert 260 parsed rows, apply them to a deep copy of the canonical state, and assert a second application creates zero animals and preserves the baseline summary.

- [ ] **Step 10: Commit the modular importer**

```powershell
git add belo-vale-ii-projeto-completo/plataforma/import_relatorio_animais.py belo-vale-ii-projeto-completo/plataforma/requirements-import.txt belo-vale-ii-projeto-completo/testes/test_import_relatorio_animais.py
git commit -m "refactor(plataforma): isolate report import domain"
```

### Task 5: Relatório de reconciliação e bloqueios de publicação

**Files:**
- Modify: `belo-vale-ii-projeto-completo/plataforma/state_contract.py`
- Modify: `belo-vale-ii-projeto-completo/plataforma/build_platform_state.py`
- Modify: `belo-vale-ii-projeto-completo/testes/test_state_contract.py`
- Modify: `belo-vale-ii-projeto-completo/plataforma/import_relatorio_animais_ultimo_relatorio.txt`

**Interfaces:**
- Produces machine-readable exit codes: `0` valid with/without warnings, `1` structural validation failure, `2` command/input error.
- Produces human-readable warning groups without mutating state.

- [ ] **Step 1: Write failing CLI behavior tests**

Use `subprocess.run` against temporary canonical files:

- duplicate IDs return exit code `1` and do not write outputs;
- valid state with 30 warnings returns `0` and prints the warning count;
- malformed JSON returns `2` with a concise error on stderr.

- [ ] **Step 2: Run tests to verify RED**

Expected: CLI exit-code assertions fail.

- [ ] **Step 3: Implement explicit error/warning handling**

Keep validation in `state_contract.py`; convert reports to CLI exit codes only in `build_platform_state.py`. Do not catch `KeyboardInterrupt` or hide tracebacks for programming errors.

- [ ] **Step 4: Regenerate the import report without changing business data**

The report must retain the 13 name divergences and 141 absent legacy animals, and add a distinct section listing the 30 DEL/situation warnings. Possible old/new pairs remain documented for human reconciliation; this task must not invent or auto-fuse candidates.

- [ ] **Step 5: Run unit and real-data validation**

Expected: all tests PASS; `validate` exits `0` with 30 warnings and zero structural errors.

- [ ] **Step 6: Commit reconciliation reporting**

```powershell
git add belo-vale-ii-projeto-completo/plataforma/state_contract.py belo-vale-ii-projeto-completo/plataforma/build_platform_state.py belo-vale-ii-projeto-completo/testes/test_state_contract.py belo-vale-ii-projeto-completo/plataforma/import_relatorio_animais_ultimo_relatorio.txt
git commit -m "feat(plataforma): report unresolved herd reconciliation"
```

### Task 6: Documentação sem fontes contraditórias

**Files:**
- Modify: `README.md`
- Modify: `belo-vale-ii-projeto-completo/README.md`
- Modify: `docs/known-issues.md`
- Modify: `docs/runbook-local.md`

**Interfaces:**
- Consumes the final file names and commands from Tasks 1–5.
- Produces a single documented source of truth for the legacy baseline.

- [ ] **Step 1: Update both READMEs**

Document 401 animals, 152 measurements, canonical/derived responsibilities, exact validation/generation commands and the fact that PONTA CURTA/GIGANTE now have `2026-07-22` readings.

- [ ] **Step 2: Update known issues**

Add the 13 name divergences, 141 legacy-only animals, unresolved old/new pairs and 30 DEL/situation warnings. Remove only issues proven resolved by tests.

- [ ] **Step 3: Update the runbook**

Add a “Legacy baseline validation” section with:

```powershell
python -m unittest belo-vale-ii-projeto-completo/testes/test_state_contract.py -v
python -m unittest belo-vale-ii-projeto-completo/testes/test_import_relatorio_animais.py -v
python belo-vale-ii-projeto-completo/plataforma/build_platform_state.py validate --canonical belo-vale-ii-projeto-completo/plataforma/state_canonical.json
```

Clarify that PostgreSQL still has not received this baseline.

- [ ] **Step 4: Run documentation consistency checks**

Search for stale statements:

```powershell
rg -n "fonte de dados definitiva|272 vacas|PONTA CURTA|GIGANTE|state_dados_atuais" README.md belo-vale-ii-projeto-completo/README.md docs
```

Review every match in context; references to historical 272-record inputs may remain only when labeled historical.

- [ ] **Step 5: Commit documentation**

```powershell
git add README.md belo-vale-ii-projeto-completo/README.md docs/known-issues.md docs/runbook-local.md docs/superpowers/specs/2026-09-17-latest-branch-stabilization-design.md docs/superpowers/plans/2026-09-17-latest-branch-stabilization.md
git commit -m "docs: define latest branch as migration baseline"
```

### Task 7: Final verification and integration readiness

**Files:**
- Verify only; no production changes expected.

**Interfaces:**
- Produces evidence that the branch is safe to review and fast-forward after approval.

- [ ] **Step 1: Run all focused Python tests**

```powershell
python -m unittest discover -s belo-vale-ii-projeto-completo/testes -p "test_state_*.py" -v
python -m unittest belo-vale-ii-projeto-completo/testes/test_import_relatorio_animais.py -v
```

Expected: all PASS.

- [ ] **Step 2: Validate generated state**

Run `build_platform_state.py validate` and confirm:

```text
animals=401
measurements=152
2026-07-22=107
2026-08-25=45
structural_errors=0
business_warnings=30
```

- [ ] **Step 3: Re-run generation and prove a clean round-trip**

Run `git diff --exit-code` before and after a second `generate`. Expected: the second generation creates no diff.

- [ ] **Step 4: Run JavaScript/vendor checks**

```powershell
node --check belo-vale-ii-projeto-completo/plataforma/vendor/pdf.min.js
node --check belo-vale-ii-projeto-completo/plataforma/vendor/pdf.worker.min.js
node --check belo-vale-ii-projeto-completo/plataforma/vendor/xlsx.full.min.js
```

Expected: all exit `0`.

- [ ] **Step 5: Run the legacy Playwright regression**

```powershell
Set-Location apps/web
npx playwright test e2e/legacy-platform.spec.ts
```

Expected: PASS with no page errors.

- [ ] **Step 6: Inspect branch scope**

```powershell
git status --short
git log --oneline origin/feature/importa-relatorio-animais..HEAD
git diff --stat origin/feature/importa-relatorio-animais...HEAD
git diff --check origin/feature/importa-relatorio-animais...HEAD
```

Expected: only stabilization code, tests, generated state and documentation; no unrelated application changes.

- [ ] **Step 7: Request code review**

Use `superpowers:requesting-code-review`. Resolve findings before proposing integration. Do not merge, push or delete worktrees without explicit user authorization.

## Plan self-review

- **Spec coverage:** Tasks 1–3 cover canonical state, invariants, deterministic ID repair and reproducible generation. Tasks 4–5 cover modular import, idempotence, structural blocking and business warnings. Task 6 resolves documentation conflicts. Task 7 supplies final verification and review evidence.
- **Placeholder scan:** no TBD/TODO/“implement later” steps; every production change has a preceding failing test and explicit command.
- **Type consistency:** `StateSummary`, `ValidationReport`, `extract_state_from_html`, `inject_state_into_html`, `summarize_state`, `validate_state`, `repair_animal_ids` and `project_state_without_history` are introduced once and reused with the same signatures.
- **Scope:** PostgreSQL migration, security/OAuth and real OCR remain separate future plans, preventing this stabilization from becoming a multi-system rewrite.
