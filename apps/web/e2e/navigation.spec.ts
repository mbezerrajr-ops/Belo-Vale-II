import { expect, test } from "@playwright/test";

import {
  E2E_ADMIN_EMAIL,
  E2E_ADMIN_PASSWORD,
  createMilkingCow,
  ensureAdminExists,
  ensureFarm,
  loginAsAdmin,
  logout,
  openArea,
  runTag,
} from "./seed";

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

  // O link aberto em outra aba abre a mesma ficha. Se a aba pedir login
  // (no Safari, o cookie seguro da sessão não vale em http://localhost; em
  // produção, é quem recebeu o link e ainda não entrou), entrar leva à ficha
  // do link, e não ao Painel.
  const other = await page.context().newPage();
  await other.goto(link);
  const entrar = other.getByRole("button", { name: "Entrar" });
  const ficha = other.getByRole("heading", { name: cow.name });
  await expect(entrar.or(ficha)).toBeVisible();
  if (await entrar.isVisible()) {
    await other.getByLabel("E-mail").fill(E2E_ADMIN_EMAIL);
    await other.getByLabel("Senha", { exact: true }).fill(E2E_ADMIN_PASSWORD);
    await entrar.click();
  }
  await expect(ficha).toBeVisible();
  await expect(other).toHaveURL(link);
  await other.close();
});

test("sair limpa o endereço", async ({ page }) => {
  await loginAsAdmin(page);
  await openArea(page, "Insumos");
  await logout(page);
  await expect(page).toHaveURL(/\/$/);
});
