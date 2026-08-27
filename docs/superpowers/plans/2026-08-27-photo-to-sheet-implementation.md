# Visão computacional para fichas de controle leiteiro — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir, em Docker, um fluxo auditável de foto de ficha leiteira para proposta revisável e medição oficial.

**Architecture:** Um frontend React envia imagens para uma API FastAPI. A API armazena objetos no MinIO, usa PostgreSQL como fonte de verdade e publica tarefas no Redis; um worker pré-processa e extrai dados por um adaptador de visão. Linhas normalizadas são validadas contra o cadastro mestre e só viram medições oficiais após revisão humana.

**Tech Stack:** React, TypeScript, Vite, FastAPI, SQLAlchemy, Alembic, PostgreSQL, Redis, Celery, MinIO, Pillow/OpenCV, pytest, Vitest, Playwright, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-08-27-photo-to-sheet-design.md`

## Global Constraints

- Toda medição passa por revisão humana na v1; confiança nunca publica automaticamente.
- PostgreSQL é a única fonte de verdade para dados oficiais; Redis não persiste domínio.
- Imagens, extrações brutas, correções e auditoria nunca são apagadas na aprovação.
- A API, e não o frontend, aplica autenticação, autorização e regras de integridade.
- Uma substituição de medição exige motivo, mantém a versão anterior e usa controle otimista de concorrência.
- Nenhum segredo, perfil ou chave de visão/OCR pode ser entregue ao navegador.
- Docker Compose deve executar toda a homologação local.

---

## Estrutura de arquivos planejada

```text
apps/
  api/
    app/
      main.py                    # composição HTTP
      core/config.py              # configurações tipadas
      db/models.py                # entidades SQLAlchemy
      db/session.py               # engine e transações
      schemas/                    # contratos Pydantic por domínio
      services/                   # ingestão, storage, validação e aprovação
      workers/tasks.py            # tarefas Celery
      vision/                     # adaptador e contrato de extração
      routers/                    # HTTP por recurso
    tests/
  web/
    src/
      api/                        # cliente HTTP tipado
      features/imports/           # upload e revisão
      features/dashboard/         # medições oficiais
infra/
  docker-compose.yml
  Dockerfile.api
  Dockerfile.web
docs/runbook-local.md
```

### Task 1: Fundação Docker, API e banco

**Files:**
- Create: `infra/docker-compose.yml`
- Create: `infra/Dockerfile.api`
- Create: `apps/api/pyproject.toml`
- Create: `apps/api/app/main.py`
- Create: `apps/api/app/core/config.py`
- Create: `apps/api/app/db/session.py`
- Create: `apps/api/tests/test_health.py`

**Interfaces:**
- Produces: `GET /healthz -> {"status":"ok"}`.
- Produces: `Settings` com URLs de PostgreSQL, Redis, MinIO e ambiente, carregadas apenas do servidor.

- [ ] **Step 1: Write the failing health test**

```python
from fastapi.testclient import TestClient
from app.main import create_app

def test_healthz_returns_ok() -> None:
    response = TestClient(create_app()).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/api && uv run pytest tests/test_health.py -v`

Expected: FAIL because `app.main` does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
from fastapi import FastAPI

def create_app() -> FastAPI:
    app = FastAPI(title="Belo Vale Ingestion API")
    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}
    return app
```

Define `Settings` with `pydantic-settings`; fail in production if a required variable is absent. Compose starts `api`, `worker`, `db`, `redis`, `minio` and `web` in a private network.

- [ ] **Step 4: Run verification**

Run: `cd apps/api && uv run pytest tests/test_health.py -v`

Expected: PASS.

Run: `docker compose -f infra/docker-compose.yml up --build -d && curl http://localhost:8000/healthz`

Expected: `{"status":"ok"}`.

- [ ] **Step 5: Commit**

```bash
git add infra apps/api
git commit -m "feat: bootstrap ingestion services"
```

### Task 2: Cadastro mestre, importações e esquema versionado

**Files:**
- Create: `apps/api/app/db/models.py`
- Create: `apps/api/alembic/versions/0001_initial_domain.py`
- Create: `apps/api/app/schemas/imports.py`
- Create: `apps/api/tests/test_models.py`

**Interfaces:**
- Produces: `Farm`, `Animal`, `Import`, `ImageAsset`, `ExtractionRun`, `ExtractedLine`, `ValidationAlert`, `ReviewDecision`, `OfficialMeasurement`, `AuditEvent`.
- Produces unique `(farm_id, sha256)` image and active `(animal_id, measured_on)` measurement constraints.

- [ ] **Step 1: Write failing persistence tests**

```python
def test_same_image_hash_cannot_be_imported_twice(session, farm) -> None:
    session.add_all([ImageAsset(farm_id=farm.id, sha256="a" * 64), ImageAsset(farm_id=farm.id, sha256="a" * 64)])
    with pytest.raises(IntegrityError):
        session.commit()

def test_measurement_version_is_unique_when_active(session, animal) -> None:
    session.add_all([
        OfficialMeasurement(animal_id=animal.id, measured_on=date(2026, 7, 22), status="active"),
        OfficialMeasurement(animal_id=animal.id, measured_on=date(2026, 7, 22), status="active"),
    ])
    with pytest.raises(IntegrityError):
        session.commit()
```

- [ ] **Step 2: Run the model tests to verify they fail**

Run: `cd apps/api && uv run pytest tests/test_models.py -v`

Expected: FAIL because domain models and migration are absent.

- [ ] **Step 3: Implement models and migration**

Use UUID primary keys, UTC timestamps and explicit foreign keys. Preserve raw extraction JSON, normalized values, confidence and crop coordinates. Model `OfficialMeasurement.status` as `active` or `superseded`; create a PostgreSQL partial unique index for the active record. Record actor, action, previous value and new value in `AuditEvent`.

- [ ] **Step 4: Run migration and persistence tests**

Run: `cd apps/api && uv run alembic upgrade head && uv run pytest tests/test_models.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api
git commit -m "feat: add auditable ingestion domain"
```

### Task 2A: Autenticação e autorização no servidor

**Files:**
- Create: `apps/api/app/core/security.py`
- Create: `apps/api/app/routers/auth.py`
- Create: `apps/api/app/schemas/auth.py`
- Modify: `apps/api/app/main.py`
- Modify: `apps/api/app/db/models.py`
- Create: `apps/api/tests/test_auth.py`

**Interfaces:**
- Produces authenticated server sessions/tokens and server-enforced `operator`, `reviewer` and `admin` roles.
- Produces dependencies consumed by every mutable route; frontend profile data is never treated as authorization.
- Consumes the database session and audit entities from Tasks 1–2.

- [ ] **Step 1: Write failing authorization tests**

Cover unauthenticated denial, role denial and permitted access for an authenticated reviewer/admin.

- [ ] **Step 2: Implement server-side identity and role enforcement**

Store only password hashes, validate credentials on the server, issue an expiring authenticated session/token, and centralize role dependencies. Do not hard-code or publish credentials.

- [ ] **Step 3: Verify**

Run: `cd apps/api && python -m pytest tests/test_auth.py -v`

Expected: PASS.

### Task 3: Ingestão segura, deduplicação e armazenamento de objetos

**Files:**
- Create: `apps/api/app/services/storage.py`
- Create: `apps/api/app/services/ingestion.py`
- Create: `apps/api/app/routers/imports.py`
- Create: `apps/api/tests/test_ingestion.py`

**Interfaces:**
- Produces: `POST /api/imports` multipart with `file`, `farm_id`, `declared_lot`, `declared_period`.
- Produces: `202 {id, status: "queued"}` on a new image.
- Produces: `409 {code: "duplicate_image", existing_import_id: UUID}` when the hash already exists for the farm — upload never silently reprocesses.
- Produces: `POST /api/imports/{existing_import_id}/reprocess` — the explicit, separate confirmation the spec requires before reprocessing a duplicate. Requires `require_minimum_role("reviewer")`. Returns `202 {id: existing_import_id, status: "queued"}` and enqueues a new `ExtractionRun` for the existing `Import`/`ImageAsset` (no re-upload). Returns `409 {code: "import_already_processing"}` if a run for that import is already queued or in progress.
- Consumes: `ImageAsset` and `Import` from Task 2.

- [ ] **Step 1: Write failing ingest tests**

```python
def test_upload_creates_queued_import(client, farm_id, valid_jpeg) -> None:
    response = client.post("/api/imports", data={"farm_id": farm_id}, files={"file": ("sheet.jpg", valid_jpeg, "image/jpeg")})
    assert response.status_code == 202
    assert response.json()["status"] == "queued"

def test_duplicate_upload_is_rejected_with_the_existing_import_id(client, farm_id, valid_jpeg) -> None:
    first = client.post("/api/imports", data={"farm_id": farm_id}, files={"file": ("sheet.jpg", valid_jpeg, "image/jpeg")})
    response = client.post("/api/imports", data={"farm_id": farm_id}, files={"file": ("sheet.jpg", valid_jpeg, "image/jpeg")})
    assert response.status_code == 409
    assert response.json()["code"] == "duplicate_image"
    assert response.json()["existing_import_id"] == first.json()["id"]

def test_reprocess_enqueues_a_new_run_for_the_existing_import(client, reviewer_token, farm_id, valid_jpeg) -> None:
    first = client.post("/api/imports", data={"farm_id": farm_id}, files={"file": ("sheet.jpg", valid_jpeg, "image/jpeg")})
    response = client.post(
        f"/api/imports/{first.json()['id']}/reprocess",
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    assert response.status_code == 202
    assert response.json() == {"id": first.json()["id"], "status": "queued"}

def test_reprocess_requires_authentication(client, farm_id, valid_jpeg) -> None:
    first = client.post("/api/imports", data={"farm_id": farm_id}, files={"file": ("sheet.jpg", valid_jpeg, "image/jpeg")})
    response = client.post(f"/api/imports/{first.json()['id']}/reprocess")
    assert response.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/api && uv run pytest tests/test_ingestion.py -v`

Expected: FAIL because the import router is absent.

- [ ] **Step 3: Implement validation and object storage**

Accept JPEG, PNG and HEIC only after content sniffing; enforce a configured maximum size and reject malformed images. Stream upload while calculating SHA-256, store original under an opaque object key, create rows transactionally and enqueue only after commit. Never expose MinIO credentials or permanent object paths to the browser. Upload never reprocesses a duplicate on its own; only the dedicated, authenticated reprocess endpoint does, per the explicit-confirmation requirement in design.md's acceptance criteria.

- [ ] **Step 4: Run tests**

Run: `cd apps/api && uv run pytest tests/test_ingestion.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api
git commit -m "feat: add photo ingestion and deduplication"
```

### Task 4: Pré-processamento e contrato de visão substituível

**Files:**
- Create: `apps/api/app/vision/contracts.py`
- Create: `apps/api/app/vision/provider.py`
- Create: `apps/api/app/services/image_preprocessing.py`
- Create: `apps/api/app/workers/tasks.py`
- Create: `apps/api/tests/test_preprocessing.py`
- Create: `apps/api/tests/test_vision_contract.py`

**Interfaces:**
- Produces: `VisionExtraction(header, lines, provider_name, model_name)`.
- Each `VisionLine` contains `animal_number`, `animal_name`, `morning`, `afternoon`, `total`, `notes`, `confidence` and `bounding_boxes`.
- Consumes: import ID from Task 3.

- [ ] **Step 1: Write failing contract tests**

```python
def test_preprocessor_normalizes_orientation(sample_photo: Path) -> None:
    output = preprocess_image(sample_photo)
    assert output.width > 0 and output.height > 0
    assert output.format == "JPEG"

def test_fake_provider_returns_structured_lines() -> None:
    result = FakeVisionProvider().extract(b"fixture")
    assert result.lines[0].morning == "10"
    assert result.lines[0].confidence["morning"] == 0.98
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/api && uv run pytest tests/test_preprocessing.py tests/test_vision_contract.py -v`

Expected: FAIL because preprocessor and provider contracts are absent.

- [ ] **Step 3: Implement worker pipeline boundaries**

Use Pillow/OpenCV to normalize EXIF rotation, correct perspective when four page corners are detected, apply contrast normalization and store derived objects. Define a provider protocol; ship a fixture provider for tests and an environment-configured adapter that cannot run without an explicit server-side key. Persist raw provider response before normalizing it.

- [ ] **Step 4: Run worker unit tests**

Run: `cd apps/api && uv run pytest tests/test_preprocessing.py tests/test_vision_contract.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api
git commit -m "feat: add image processing and vision contract"
```

### Task 5: Normalização, conciliação de animal e validações explicáveis

**Files:**
- Create: `apps/api/app/services/normalization.py`
- Create: `apps/api/app/services/animal_matching.py`
- Create: `apps/api/app/services/validation.py`
- Create: `apps/api/tests/test_normalization.py`
- Create: `apps/api/tests/test_validation.py`

**Interfaces:**
- Produces: `NormalizedLine` and `ValidationResult(final_confidence, alerts, candidate_animal_id)`.
- Produces alert codes: `unknown_animal`, `ambiguous_animal`, `lot_mismatch`, `missing_header`, `total_mismatch`, `duplicate_measurement`, `implausible_value`, `missing_required_value`.

- [ ] **Step 1: Write failing domain tests**

```python
def test_normalize_decimal_comma_and_date() -> None:
    line = normalize_line(raw_total="18,5", raw_date="22/07/26")
    assert line.total == Decimal("18.5")
    assert line.measured_on == date(2026, 7, 22)

def test_total_mismatch_is_an_explained_alert(animal) -> None:
    result = validate_line(line(morning=10, afternoon=8, total=25), animal=animal, history=[])
    assert result.has_code("total_mismatch")
    assert result.alerts[0].details["expected_total"] == "18"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/api && uv run pytest tests/test_normalization.py tests/test_validation.py -v`

Expected: FAIL because domain services are absent.

- [ ] **Step 3: Implement deterministic domain rules**

Normalize decimal commas and two-digit dates using a configured century window. Match first by exact tag/number, then normalized name, and mark multiple candidates ambiguous. Validate arithmetic using a configured decimal tolerance. Calculate confidence from separate named factors and persist all inputs; never hide a hard alert behind a high score.

- [ ] **Step 4: Run tests**

Run: `cd apps/api && uv run pytest tests/test_normalization.py tests/test_validation.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api
git commit -m "feat: validate normalized milk measurements"
```

### Task 6: Revisão, aprovação idempotente e substituição auditável

**Files:**
- Create: `apps/api/app/services/review.py`
- Create: `apps/api/app/services/approval.py`
- Create: `apps/api/app/routers/reviews.py`
- Create: `apps/api/tests/test_approval.py`

**Interfaces:**
- Produces: `GET /api/imports/{id}/review` with raw values, normalized values, crop URLs, alerts and recent history.
- Produces: `POST /api/extracted-lines/{id}/decision` with `{action, corrected_values, reason, expected_version}`.

- [ ] **Step 1: Write failing approval tests**

```python
def test_approval_supersedes_existing_measurement(session, reviewer, line, active_measurement) -> None:
    result = approve_line(session, line.id, reviewer.id, reason="correção confirmada", expected_version=line.version)
    assert result.measurement.status == "active"
    session.refresh(active_measurement)
    assert active_measurement.status == "superseded"

def test_approval_rejects_stale_version(session, reviewer, line) -> None:
    with pytest.raises(ConcurrentReviewError):
        approve_line(session, line.id, reviewer.id, reason="x", expected_version=line.version - 1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/api && uv run pytest tests/test_approval.py -v`

Expected: FAIL because approval service is absent.

- [ ] **Step 3: Implement review transactions**

Use one database transaction with a row lock for the line and active measurement. Require a non-empty reason on replacement, mark old measurement superseded, create new active measurement, record original/corrected values and actor in audit events, and reject duplicate or stale decisions with HTTP 409.

- [ ] **Step 4: Run tests**

Run: `cd apps/api && uv run pytest tests/test_approval.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api
git commit -m "feat: add reviewed measurement approval"
```

### Task 7: Frontend de upload e revisão de linhas

**Files:**
- Create: `apps/web/package.json`
- Create: `apps/web/src/api/client.ts`
- Create: `apps/web/src/features/imports/UploadForm.tsx`
- Create: `apps/web/src/features/imports/ReviewWorkspace.tsx`
- Create: `apps/web/src/features/imports/ReplacementWarning.tsx`
- Create: `apps/web/src/features/imports/imports.test.tsx`

**Interfaces:**
- Consumes: `POST /api/imports`, `GET /api/imports/{id}/review`, `POST /api/extracted-lines/{id}/decision`.
- Produces: upload status, duplicate warning, row-level approval/correction/rejection UI and explicit replacement confirmation.

- [ ] **Step 1: Write failing UI test**

```tsx
it("shows the replacement warning before approval", async () => {
  render(<ReviewWorkspace review={reviewWithExistingMeasurement} />)
  await userEvent.click(screen.getByRole("button", { name: "Aprovar" }))
  expect(screen.getByText(/será substituída/i)).toBeVisible()
  expect(screen.getByLabelText(/motivo da substituição/i)).toBeRequired()
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/web && npm test -- imports.test.tsx`

Expected: FAIL because the workspace is absent.

- [ ] **Step 3: Implement review-first UI**

Render original image and line crop side by side with raw OCR, normalized values, confidence factors, alerts and recent animal history. Pre-fill corrections but require deliberate action. Disable final approval until replacement reason is supplied when an active measurement exists. Show queued, processing, failed and ready import states.

- [ ] **Step 4: Run frontend tests**

Run: `cd apps/web && npm test -- imports.test.tsx`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web
git commit -m "feat: add import review workspace"
```

### Task 8: Leituras oficiais para dashboard e integração ponta a ponta

**Files:**
- Create: `apps/api/app/routers/measurements.py`
- Create: `apps/api/tests/test_measurement_history.py`
- Create: `apps/web/src/features/dashboard/OfficialMeasurements.tsx`
- Create: `apps/web/e2e/import-review.spec.ts`
- Create: `docs/runbook-local.md`

**Interfaces:**
- Produces: `GET /api/measurements?farm_id=&from=&to=` returning active measurements only.
- Consumes: approved `OfficialMeasurement` from Task 6.

- [ ] **Step 1: Write failing API and e2e tests**

```python
def test_history_hides_superseded_measurements(client, farm, active_measurement, superseded_measurement) -> None:
    response = client.get(f"/api/measurements?farm_id={farm.id}")
    assert [item["id"] for item in response.json()] == [str(active_measurement.id)]
```

```ts
test("reviewed import creates an active measurement visible in history", async ({ page }) => {
  await page.goto("/imports/new")
  await page.setInputFiles('input[type="file"]', "fixtures/lote-1.jpg")
  await page.getByRole("button", { name: "Enviar foto" }).click()
  await page.getByRole("button", { name: "Aprovar" }).first().click()
  await expect(page.getByText("Medição oficial ativa")).toBeVisible()
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/api && uv run pytest tests/test_measurement_history.py -v`

Expected: FAIL because the measurements endpoint is absent.

Run: `cd apps/web && npx playwright test e2e/import-review.spec.ts`

Expected: FAIL because the complete flow is absent.

- [ ] **Step 3: Implement official read model and runbook**

Expose only active official measurements to dashboard consumers. Add index-backed date/farm queries. Document Docker startup, Alembic migration, MinIO bucket initialization, fixtures, backup of PostgreSQL/object storage, and the policy that automatic approval is disabled in v1.

- [ ] **Step 4: Run full verification**

Run: `cd apps/api && uv run pytest -v`

Expected: PASS.

Run: `cd apps/web && npm test && npx playwright test`

Expected: PASS.

Run: `docker compose -f infra/docker-compose.yml up --build -d`

Expected: all services healthy and API returns `{"status":"ok"}`.

- [ ] **Step 5: Commit**

```bash
git add apps docs infra
git commit -m "feat: expose reviewed measurements"
```

## Plan self-review

- Spec coverage: Tasks 1–8 cover Docker, backend security, ingestão, hash, fila, pré-processamento, adaptador de visão, extração bruta, normalização, validação, confiança explicável, revisão, auditoria, substituição, dado oficial e dashboard.
- Intentionally deferred: treinamento/fine-tuning, aprovação automática e migração completa da UI Artifact; o spec os exclui da v1.
- Type consistency: `VisionExtraction` flows to `NormalizedLine`, then `ValidationResult`, then review and `OfficialMeasurement`. `expected_version` is consistently used for optimistic review concurrency.

