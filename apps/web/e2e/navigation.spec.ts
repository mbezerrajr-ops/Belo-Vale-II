import { expect, test } from "@playwright/test";

import { createMilkingCow, ensureAdminExists, ensureFarm, loginAsAdmin, logout, openArea, runTag } from "./seed";

// Cada tela tem endereço. Sem isso, recarregar voltava ao Painel, o voltar do
// Android fechava o app aberto pela tela inicial e não havia link de ficha.

const TAG = runTag();
let cow: { brinco: string; name: string };

test.beforeAll(() => {
  ensureAdminExists();
  ensureFarm();
  cow = createMilkingCow(`${TAG}N`);
});

test("recarregar mantém a área", async ({ page }) => {
  await loginAsAdmin(page);
  await openArea(page, "Insumos");
  await expect(page).toHaveURL(/\/insumos$/);

  await page.reload();

  await expect(page.getByRole("heading", { name: "Insumos e dieta" })).toBeVisible();
  await expect(page).toHaveTitle("Insumos · Belo Vale II");
});

test("ficha tem link; voltar devolve a busca como estava", async ({ page }) => {
  await loginAsAdmin(page);
  await openArea(page, "Animais");
  await page.getByLabel("Brinco ou nome").fill(cow.name);
  await page.getByRole("button", { name: "Buscar", exact: true }).click();
  await page.getByRole("button", { name: new RegExp(cow.name) }).click();

  await expect(page.getByRole("heading", { name: cow.name })).toBeVisible();
  await expect(page).toHaveURL(/\/animais\/[0-9a-f-]{36}$/);
  const link = page.url();

  // O voltar do navegador (e o gesto do Android) volta para a busca, com o
  // que foi digitado e o resultado ainda na tela.
  await page.goBack();
  await expect(page).toHaveURL(/\/animais$/);
  await expect(page.getByLabel("Brinco ou nome")).toHaveValue(cow.name);
  await expect(page.getByRole("button", { name: new RegExp(cow.name) })).toBeVisible();

  await page.goForward();
  await expect(page.getByRole("heading", { name: cow.name })).toBeVisible();

  // Recarregar a ficha continua na ficha.
  await page.reload();
  await expect(page.getByRole("heading", { name: cow.name })).toBeVisible();

  // O link aberto em outra aba abre a mesma ficha.
  const other = await page.context().newPage();
  await other.goto(link);
  await expect(other.getByRole("heading", { name: cow.name })).toBeVisible();
  await other.close();
});

test("sair limpa o endereço", async ({ page }) => {
  await loginAsAdmin(page);
  await openArea(page, "Insumos");
  await logout(page);
  await expect(page).toHaveURL(/\/$/);
});
