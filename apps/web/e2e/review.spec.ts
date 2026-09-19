import { expect, test } from "@playwright/test";

import {
  createMilkingCow,
  daysAgo,
  ensureAdminExists,
  ensureFarm,
  loadProposals,
  loginAsAdmin,
  openArea,
  runTag,
} from "./seed";

// Caixa de revisão de ponta a ponta: uma leitura entra pelo comando de carga
// (a mesma porta que os leitores de foto e áudio usarão), aparece na caixa,
// e só vira dado do rebanho depois de aprovada por uma pessoa.

test.describe.configure({ mode: "serial" });

const TAG = runTag();
const LABEL = `caderno ${TAG}`;
const DAY = daysAgo(2);
// Folha cuja data o leitor errou: uns dois anos antes (como 2026 lido 2024).
const SHEET_LABEL = `folha ${TAG}`;
const WRONG_DAY = daysAgo(2 + 731);
const br = (iso: string): string => iso.split("-").reverse().join("/");

let withBrinco: { brinco: string; name: string };
let onlyName: { brinco: string; name: string };
let sheetCow: { brinco: string; name: string };

test.beforeAll(() => {
  ensureAdminExists();
  ensureFarm();
  withBrinco = createMilkingCow(`${TAG}R`);
  onlyName = createMilkingCow(`${TAG}S`);
  sheetCow = createMilkingCow(`${TAG}T`);
  loadProposals(
    {
      extractor_name: "e2e",
      reference_date: DAY,
      events: [
        {
          event_type: "production",
          brinco: withBrinco.brinco,
          fields: { producao: "215" },
          evidence: { text: `${withBrinco.brinco} 215` },
          confidence: { producao: 0.4 },
        },
        {
          event_type: "note",
          nome: onlyName.name,
          fields: { texto: "mancando da pata traseira" },
          evidence: { text: `${onlyName.name} mancando da pata traseira` },
        },
      ],
    },
    LABEL,
  );
  loadProposals(
    {
      extractor_name: "e2e",
      reference_date: WRONG_DAY,
      events: [
        {
          event_type: "production",
          brinco: sheetCow.brinco,
          fields: { producao: "12", parcelas: "7 + 5" },
          evidence: { text: `${sheetCow.brinco} 7 + 5 = 12` },
        },
      ],
    },
    SHEET_LABEL,
  );
});

test("produção lida entra só depois de corrigida e aprovada", async ({ page }) => {
  await loginAsAdmin(page);
  await expect(page.getByRole("navigation", { name: "Áreas" }).getByLabel(/pendentes/)).toBeVisible();
  await openArea(page, /Revisão/);

  await expect(page.getByRole("heading", { name: new RegExp(LABEL) })).toBeVisible();
  const card = page.getByRole("article", { name: `Produção — ${withBrinco.brinco}` });
  await expect(card).toContainText(`${withBrinco.brinco} 215`);
  await expect(card).toContainText("confiança baixa");

  await card.getByLabel("Litros").fill("21,5");
  await card.getByRole("button", { name: "Aprovar" }).click();
  await expect(card).toHaveCount(0);

  // A leitura aprovada aparece na ficha, com a origem.
  await openArea(page, "Animais");
  await page.getByLabel("Brinco ou nome").fill(withBrinco.name);
  await page.getByRole("button", { name: "Buscar" }).click();
  await page.getByRole("button", { name: new RegExp(withBrinco.name) }).click();
  const readings = page.getByRole("table", { name: "Leituras de produção" });
  await expect(readings).toContainText("21,5");
  await expect(readings).toContainText("Leitura revisada");
});

test("observação só com o nome exige escolher o animal", async ({ page }) => {
  await loginAsAdmin(page);
  await openArea(page, /Revisão/);

  const card = page.getByRole("article", { name: `Observação — ${onlyName.name}` });
  const approve = card.getByRole("button", { name: "Aprovar" });
  await expect(approve).toBeDisabled();

  await card.getByRole("button", { name: new RegExp(`É esta: ${onlyName.brinco}`) }).click();
  await approve.click();
  await expect(card).toHaveCount(0);

  await page.getByRole("button", { name: "Aprovadas" }).click();
  const decided = page.locator(".decided-item", { hasText: onlyName.name });
  await expect(decided).toContainText("mancando da pata traseira");
  await expect(decided).toContainText("Aprovada por e2e@belovale.test");
});

test("filtra por arquivo e troca a data do arquivo inteiro", async ({ page }) => {
  await loginAsAdmin(page);
  await openArea(page, /Revisão/);

  const files = page.getByRole("group", { name: "Arquivos" });
  await files.getByRole("button", { name: new RegExp(SHEET_LABEL) }).click();
  await expect(page.getByRole("heading", { name: new RegExp(LABEL) })).toHaveCount(0);

  const card = page.getByRole("article", { name: `Produção — ${sheetCow.brinco}` });
  await expect(card).toContainText("ordenhas 7 + 5");
  await expect(card).toContainText("mais de 6 meses");

  await page.getByRole("button", { name: "Trocar data do arquivo" }).click();
  await page.getByLabel("Nova data do arquivo").fill(DAY);
  await page.getByRole("button", { name: /Aplicar às 1 pendente/ }).click();

  const heading = page.getByRole("heading", { name: new RegExp(SHEET_LABEL) });
  await expect(heading).toContainText(br(DAY));
  await expect(page.getByText(`lida como ${br(WRONG_DAY)}`, { exact: false })).toBeVisible();
  await expect(card).not.toContainText("mais de 6 meses");
});
