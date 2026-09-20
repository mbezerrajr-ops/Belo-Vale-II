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

// Foto da folha até a medição oficial, de ponta a ponta, na pilha real:
// envio pela Revisão, worker de verdade (Celery sobre Redis), leitor **falso**
// (o CI não tem GPU nem modelo), proposta na caixa, aprovação e leitura
// oficial com proveniência de revisão.
//
// O leitor falso devolve sempre a mesma vaca (497 PONTA CURTA, 18 L), que é a
// mesma que o seed cadastra — é o que permite exercitar o caminho inteiro sem
// depender de reconhecimento de imagem.

const currentDir = path.dirname(fileURLToPath(import.meta.url));
const FIXTURE_SHEET = path.join(currentDir, "fixtures", "sheet.jpg");
// Outra imagem (outros bytes): o primeiro envio do teste de duplicidade não
// colide com a FIXTURE_SHEET já usada.
const FIXTURE_SHEET_2 = path.join(currentDir, "fixtures", "sheet2.jpg");

test.describe("foto da folha até a medição oficial", () => {
  test.beforeAll(() => {
    ensureAdminExists();
    ensurePhotoSheetAnimal();
  });

  test("envio pela Revisão, leitura pelo worker, aprovação e medição oficial", async ({ page }) => {
    await loginAsAdmin(page);
    await openArea(page, /Revisão/);

    await page.getByRole("button", { name: "Enviar foto" }).click();
    // Uma cópia com sufixo único: Postgres e MinIO persistem entre execuções,
    // e os mesmos bytes cairiam na proteção contra foto duplicada.
    await page.getByLabel(/foto da folha/i).setInputFiles(uniqueFixtureCopy(FIXTURE_SHEET));
    await page.getByRole("button", { name: "Enviar", exact: true }).click();
    await expect(page.getByText(/lendo a folha/i)).toBeVisible();

    // O worker lê em segundo plano: a caixa é relida pelo botão "Atualizar"
    // até a proposta aparecer, sem espera fixa. É o mesmo gesto que a pessoa
    // faz na fazenda enquanto a leitura não termina.
    const card = page.getByRole("article", { name: new RegExp(`Produção — 497`) }).first();
    const refresh = page.getByRole("button", { name: "Atualizar", exact: true });
    await expect(async () => {
      await refresh.click();
      await expect(card).toBeVisible({ timeout: 2_000 });
    }).toPass({ timeout: 45_000, intervals: [500, 1000, 2000] });

    await expect(card).toContainText(E2E_ANIMAL_NAME, { ignoreCase: true });

    // O leitor falso devolve sempre o mesmo animal e data: uma execução
    // anterior pode já ter lançado essa produção, e aí a API exige motivo.
    await card.getByRole("button", { name: "Aprovar" }).click();
    const replaceReason = card.getByLabel(/motivo para substituir/i);
    if (await replaceReason.isVisible()) {
      await replaceReason.fill("E2E: confirmando substituição de execução anterior");
      await card.getByRole("button", { name: /substituir e aprovar/i }).click();
    }
    // Não se afirma que o cartão some: o leitor falso devolve sempre a mesma
    // vaca, e execuções anteriores deixam pendências iguais na caixa. O que
    // prova a aprovação é a medição oficial, conferida logo abaixo.

    // A medição aprovada aparece na leitura oficial, não só na revisão.
    await openArea(page, "Medições");
    const official = page.getByRole("region", { name: "Medições oficiais" });
    await expect(async () => {
      await official.getByRole("button", { name: "Atualizar", exact: true }).click();
      await expect(official).toContainText("18,0 L");
    }).toPass({ timeout: 15_000, intervals: [500, 1000] });
    await expect(official).toContainText(E2E_ANIMAL_NAME);
  });

  test("a mesma foto enviada duas vezes é lida de novo, sem duplicar", async ({ page }) => {
    await loginAsAdmin(page);
    await openArea(page, /Revisão/);

    const sheet = uniqueFixtureCopy(FIXTURE_SHEET_2);
    await page.getByRole("button", { name: "Enviar foto" }).click();
    await page.getByLabel(/foto da folha/i).setInputFiles(sheet);
    await page.getByRole("button", { name: "Enviar", exact: true }).click();
    await expect(page.getByText(/lendo a folha/i)).toBeVisible();

    // Mesmos bytes: o backend reconhece pelo hash e não cria outra cópia.
    await page.getByRole("button", { name: "Enviar foto" }).click();
    await page.getByLabel(/foto da folha/i).setInputFiles(sheet);
    await page.getByRole("button", { name: "Enviar", exact: true }).click();
    await expect(page.getByText(/já foi enviada/i)).toBeVisible();

    // Ler de novo é deliberado. Se a primeira leitura ainda estiver rodando,
    // a API recusa e a tela pede para tentar de novo — como faria uma pessoa.
    await expect(async () => {
      await page.getByRole("button", { name: "Ler de novo" }).click();
      await expect(page.getByText(/lendo a folha/i)).toBeVisible({ timeout: 2_000 });
    }).toPass({ timeout: 45_000, intervals: [1_000, 2_000, 3_000] });
  });
});
