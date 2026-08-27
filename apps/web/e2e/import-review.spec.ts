import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

import {
  E2E_ADMIN_EMAIL,
  E2E_ADMIN_PASSWORD,
  E2E_ANIMAL_NAME,
  ensureAdminExists,
  ensureFarmAndAnimal,
} from "./seed";
import { uniqueFixtureCopy } from "./testFiles";

const currentDir = path.dirname(fileURLToPath(import.meta.url));
const FIXTURE_SHEET = path.join(currentDir, "fixtures", "sheet.jpg");
// A distinct image (different bytes/hash) so the duplicate-upload test's own
// *first* upload doesn't collide with FIXTURE_SHEET already used elsewhere.
const FIXTURE_SHEET_2 = path.join(currentDir, "fixtures", "sheet2.jpg");

test.describe("photo-to-official-measurement", () => {
  let farmId: string;

  test.beforeAll(() => {
    ensureAdminExists();
    ({ farmId } = ensureFarmAndAnimal());
  });

  test("upload, worker extraction, review, approval, and dashboard visibility", async ({
    page,
  }) => {
    // 1-2. App loads, user logs in for real against POST /api/auth/login.
    await page.goto("/");
    await page.getByLabel("E-mail").fill(E2E_ADMIN_EMAIL);
    await page.getByLabel("Senha").fill(E2E_ADMIN_PASSWORD);
    await page.getByRole("button", { name: "Entrar" }).click();
    await expect(page.getByText(E2E_ADMIN_EMAIL)).toBeVisible();

    // 3-4. Upload a real image; the API creates the import.
    // Two "Fazenda" fields exist on this page (the dashboard filter, then
    // the upload form) — this is the upload form's own field.
    await page.getByLabel("Fazenda").nth(1).fill(farmId);
    // A fresh, uniquely-suffixed copy: Postgres/MinIO persist across E2E
    // runs, so reusing the exact same bytes would hit real duplicate-image
    // protection from a previous run instead of exercising a fresh upload.
    await page.getByLabel("Foto da ficha").setInputFiles(uniqueFixtureCopy(FIXTURE_SHEET));
    await page.getByRole("button", { name: "Enviar foto" }).click();
    await expect(page.getByText(/Importação enviada/i)).toBeVisible();

    // 5-8. The worker (real Celery, real Redis, FakeVisionProvider adapter)
    // processes the upload asynchronously; poll the real state via the UI's
    // own refresh action instead of a fixed sleep.
    const lineLocator = page.getByRole("article", { name: /Linha 1/i });
    await expect(async () => {
      await page.getByRole("button", { name: "Atualizar revisão" }).click();
      await expect(lineLocator).toBeVisible();
    }).toPass({ timeout: 30_000, intervals: [500, 1000, 2000] });

    // The extracted, normalized data is shown next to the review controls.
    await expect(lineLocator.getByText("18")).toBeVisible();
    await expect(lineLocator).toContainText(E2E_ANIMAL_NAME, { ignoreCase: true });

    // 9-10. Approve. FakeVisionProvider always returns the same animal+date,
    // so a persistent environment may already have an active measurement
    // from an earlier run of this very suite — the UI must require a reason
    // in that case, and approve directly otherwise. Either way the backend
    // decides this, never the frontend.
    await lineLocator.getByRole("button", { name: "Aprovar" }).click();
    const replacementReason = lineLocator.getByLabel(/motivo da substituição/i);
    if (await replacementReason.isVisible()) {
      await replacementReason.fill("E2E: confirmando substituição de execução anterior");
    }
    await lineLocator.getByRole("button", { name: "Confirmar aprovação" }).click();

    // 11. The approved measurement becomes visible through the read-only
    // dashboard endpoint, not just the review screen that created it.
    await page.getByLabel("Fazenda").first().fill(farmId);
    const dashboard = page.getByRole("region", { name: "Medições oficiais" });
    await expect(async () => {
      await dashboard.getByRole("button", { name: "Atualizar", exact: true }).click();
      await expect(dashboard.getByText(/18 L/)).toBeVisible();
    }).toPass({ timeout: 10_000, intervals: [500, 1000] });
  });

  test("uploading the same photo twice is rejected as a duplicate, with a controlled reprocess path", async ({
    page,
  }) => {
    await page.goto("/");
    await page.getByLabel("E-mail").fill(E2E_ADMIN_EMAIL);
    await page.getByLabel("Senha").fill(E2E_ADMIN_PASSWORD);
    await page.getByRole("button", { name: "Entrar" }).click();
    await expect(page.getByText(E2E_ADMIN_EMAIL)).toBeVisible();

    const uniqueSheet = uniqueFixtureCopy(FIXTURE_SHEET_2);

    await page.getByLabel("Fazenda").nth(1).fill(farmId);
    await page.getByLabel("Foto da ficha").setInputFiles(uniqueSheet);
    await page.getByRole("button", { name: "Enviar foto" }).click();
    await expect(page.getByText(/Importação enviada/i)).toBeVisible();

    // Same bytes, same farm: the backend must recognize this by content
    // hash and refuse to silently create a second import.
    await page.getByLabel("Foto da ficha").setInputFiles(uniqueSheet);
    await page.getByRole("button", { name: "Enviar foto" }).click();
    await expect(page.getByText(/já foi enviada anteriormente/i)).toBeVisible();

    // Reprocessing is a distinct, deliberate action — not an automatic
    // consequence of the duplicate upload — and targets the *original*
    // import rather than creating an unrelated new one.
    await page.getByRole("button", { name: "Reprocessar mesmo assim" }).click();
    await expect(page.getByText(/Importação enviada/i)).toBeVisible();
  });
});
