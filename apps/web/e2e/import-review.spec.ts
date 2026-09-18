import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

import {
  E2E_ANIMAL_NAME,
  ensureAdminExists,
  ensurePhotoSheetAnimal,
  loginAsAdmin,
  openArea,
} from "./seed";
import { uniqueFixtureCopy } from "./testFiles";

// Fluxo de ficha por foto, de ponta a ponta: upload, worker real (Celery sobre
// Redis), provedor de OCR falso, revisão, aprovação e leitura oficial.
//
// A área "Fichas" só aparece com OCR real; aqui ela está visível porque o
// ambiente E2E liga PHOTO_SHEETS_DEMO de propósito (infra/.env.e2e).

const currentDir = path.dirname(fileURLToPath(import.meta.url));
const FIXTURE_SHEET = path.join(currentDir, "fixtures", "sheet.jpg");
// Outra imagem (outros bytes): o primeiro envio do teste de duplicidade não
// colide com a FIXTURE_SHEET já usada.
const FIXTURE_SHEET_2 = path.join(currentDir, "fixtures", "sheet2.jpg");

test.describe("ficha por foto até a medição oficial", () => {
  test.beforeAll(() => {
    ensureAdminExists();
    ensurePhotoSheetAnimal();
  });

  test("envio, leitura pelo worker, revisão, aprovação e medição oficial", async ({ page }) => {
    await loginAsAdmin(page);
    await openArea(page, "Fichas");

    // Uma cópia com sufixo único: Postgres e MinIO persistem entre execuções,
    // e os mesmos bytes cairiam na proteção contra foto duplicada.
    await page.getByLabel("Foto da ficha").setInputFiles(uniqueFixtureCopy(FIXTURE_SHEET));
    await page.getByRole("button", { name: "Enviar foto" }).click();
    await expect(page.getByText(/Importação enviada/i)).toBeVisible();

    // O worker processa de forma assíncrona: a tela é atualizada pela própria
    // ação de "Atualizar revisão", sem espera fixa.
    const line = page.getByRole("article", { name: /Linha 1/i });
    await expect(async () => {
      await page.getByRole("button", { name: "Atualizar revisão" }).click();
      await expect(line).toBeVisible();
    }).toPass({ timeout: 45_000, intervals: [500, 1000, 2000] });

    await expect(line.getByText("18")).toBeVisible();
    await expect(line).toContainText(E2E_ANIMAL_NAME, { ignoreCase: true });

    // O OCR falso devolve sempre o mesmo animal e data: uma execução anterior
    // pode já ter criado essa medição, e aí o backend exige motivo.
    await line.getByRole("button", { name: "Aprovar" }).click();
    const replacementReason = line.getByLabel(/motivo da substituição/i);
    if (await replacementReason.isVisible()) {
      await replacementReason.fill("E2E: confirmando substituição de execução anterior");
    }
    await line.getByRole("button", { name: "Confirmar aprovação" }).click();

    // A medição aprovada aparece na leitura oficial, não só na tela de revisão.
    await openArea(page, "Medições");
    const official = page.getByRole("region", { name: "Medições oficiais" });
    await expect(async () => {
      await official.getByRole("button", { name: "Atualizar", exact: true }).click();
      await expect(official).toContainText("18,0 L");
    }).toPass({ timeout: 15_000, intervals: [500, 1000] });
    await expect(official).toContainText(E2E_ANIMAL_NAME);
  });

  test("a mesma foto enviada duas vezes é recusada, com reprocessamento deliberado", async ({ page }) => {
    await loginAsAdmin(page);
    await openArea(page, "Fichas");

    const uniqueSheet = uniqueFixtureCopy(FIXTURE_SHEET_2);
    await page.getByLabel("Foto da ficha").setInputFiles(uniqueSheet);
    await page.getByRole("button", { name: "Enviar foto" }).click();
    await expect(page.getByText(/Importação enviada/i)).toBeVisible();

    // Mesmos bytes: o backend reconhece pelo hash e não cria outra importação.
    await page.getByLabel("Foto da ficha").setInputFiles(uniqueSheet);
    await page.getByRole("button", { name: "Enviar foto" }).click();
    await expect(page.getByText(/já foi enviada anteriormente/i)).toBeVisible();

    // Reprocessar é uma ação separada e deliberada, sobre a importação original.
    // Se a leitura da primeira foto ainda estiver rodando no worker, a API
    // recusa e a tela pede para tentar de novo — como faria uma pessoa.
    await expect(async () => {
      await page.getByRole("button", { name: "Reprocessar mesmo assim" }).click();
      await expect(page.getByText(/Importação enviada/i)).toBeVisible({ timeout: 2_000 });
    }).toPass({ timeout: 45_000, intervals: [1_000, 2_000, 3_000] });
  });
});
