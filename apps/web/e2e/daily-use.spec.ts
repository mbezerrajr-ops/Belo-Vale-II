import { expect, test } from "@playwright/test";

import {
  createMilkingCow,
  ensureAdminExists,
  ensureFarm,
  login,
  loginAsAdmin,
  logout,
  openArea,
  runTag,
} from "./seed";

// Uso diário, de ponta a ponta, no navegador real contra a pilha real:
// primeiro acesso de uma conta nova, lançamento de produção no curral,
// correção pela ficha do animal, importação de planilha, baixa e senha
// provisória. Os testes dependem uns dos outros (a conta criada no primeiro
// é usada nos seguintes), por isso rodam em série.
//
// Cada execução cria as próprias contas e vacas: o banco persiste entre
// execuções, e reaproveitar dados faria a segunda rodada esbarrar na primeira.

test.describe.configure({ mode: "serial" });

const TAG = runTag();
const OPERATOR = `op${TAG}@belovale.test`;
// A política recusa "senha" dentro da senha: a inicial também precisa passar.
const INITIAL = "capim novo do joao";
const CHOSEN = "pitomba madura no pe";

let milkingCow: { brinco: string; name: string };
let importedCow: { brinco: string; name: string };

test.beforeAll(() => {
  ensureAdminExists();
  ensureFarm();
  milkingCow = createMilkingCow(`${TAG}A`);
  importedCow = createMilkingCow(`${TAG}B`);
});

test("conta nova escolhe a própria senha no primeiro acesso", async ({ page }) => {
  await loginAsAdmin(page);
  await openArea(page, "Contas");
  await page.getByRole("button", { name: "Nova conta" }).click();
  await page.getByLabel("E-mail").fill(OPERATOR);
  await page.getByLabel("Senha", { exact: true }).fill(INITIAL);
  await page.getByLabel("Função").selectOption("operator");
  await page.getByRole("button", { name: "Criar conta" }).click();
  await expect(page.getByText(`Conta criada para ${OPERATOR}.`)).toBeVisible();
  await logout(page);

  await login(page, OPERATOR, INITIAL);
  await expect(page.getByRole("heading", { name: "Escolha uma senha nova" })).toBeVisible();
  // Antes de trocar, nada do resto do aplicativo aparece.
  await expect(page.getByRole("navigation", { name: "Áreas" })).toHaveCount(0);

  await page.getByLabel("Senha atual").fill(INITIAL);
  await page.getByLabel("Nova senha").fill(CHOSEN);
  await page.getByRole("button", { name: "Trocar senha" }).click();

  // Funcionário abre direto no lançamento de produção.
  await expect(page.getByRole("heading", { name: "Produção do dia" })).toBeVisible();
});

test("funcionário lança a produção no curral e imprime a folha", async ({ page }) => {
  await login(page, OPERATOR, CHOSEN);
  await expect(page.getByRole("heading", { name: "Produção do dia" })).toBeVisible();

  await page.getByRole("group", { name: "Lote de ordenha" }).getByRole("button", { name: "LOTE 3" }).click();
  const field = page.getByLabel(`Litros de ${milkingCow.name}`);
  await field.fill("21,5");
  await field.press("Enter");

  const row = page.locator("li", { has: field });
  await expect(row.getByLabel("salvo")).toBeVisible();

  // A folha em branco é montada para a impressora; aqui só conferimos que a
  // vaca está nela, sem abrir o diálogo de impressão do navegador.
  await page.evaluate(() => {
    window.print = () => undefined;
  });
  await page.getByRole("button", { name: "Imprimir folha em branco" }).click();
  await expect(page.locator(".print-area")).toContainText(milkingCow.name);
});

test("revisor corrige a leitura pela ficha do animal", async ({ page }) => {
  await loginAsAdmin(page);
  await openArea(page, "Animais");
  await page.getByLabel("Brinco ou nome").fill(milkingCow.name);
  await page.getByRole("button", { name: "Buscar" }).click();
  await page.getByRole("button", { name: new RegExp(milkingCow.name) }).click();

  const readings = page.getByRole("table", { name: "Leituras de produção" });
  await expect(readings).toContainText("21,5");
  await expect(readings).toContainText("Digitada");

  await readings.getByRole("button", { name: "Corrigir" }).click();
  await page.getByLabel("Novo valor (L)").fill("20");
  await page.getByLabel("Motivo").fill("E2E: conferido com o tanque");
  await page.getByRole("button", { name: "Salvar correção" }).click();

  await expect(readings).toContainText("corrigida");
  await expect(readings).toContainText("E2E: conferido com o tanque");
  await expect(page.getByText("Versões anteriores (1)")).toBeVisible();
});

test("importação de planilha com prévia antes de gravar", async ({ page }) => {
  await loginAsAdmin(page);
  await openArea(page, "Produção");
  await page.getByRole("button", { name: "Importar arquivo" }).click();

  await page.getByLabel("Arquivo (CSV, XLSX ou PDF)").setInputFiles({
    name: `coleta-${TAG}.csv`,
    mimeType: "text/csv",
    buffer: Buffer.from(`Número;Nome;Produção\n${importedCow.brinco};${importedCow.name};18,5\n`),
  });
  await page.getByRole("button", { name: "Ver prévia" }).click();

  const preview = page.getByRole("table", { name: "Prévia da importação" });
  await expect(preview).toContainText(importedCow.name);
  await expect(preview).toContainText("Nova");

  await page.getByRole("button", { name: "Importar 1 leitura" }).click();
  await expect(page.getByText(/Importação concluída: 1 leitura nova/)).toBeVisible();
  await expect(page.getByText(`coleta-${TAG}.csv`)).toBeVisible();
});

test("baixa de animal e desfazer", async ({ page }) => {
  await loginAsAdmin(page);
  await openArea(page, "Animais");
  await page.getByLabel("Brinco ou nome").fill(importedCow.name);
  await page.getByRole("button", { name: "Buscar" }).click();
  await page.getByRole("button", { name: new RegExp(importedCow.name) }).click();

  await page.getByRole("button", { name: "Mais ações" }).click();
  await page.getByRole("button", { name: "Dar baixa" }).click();
  await page.getByLabel("Motivo da baixa").selectOption("venda");
  await page.getByRole("button", { name: "Confirmar baixa" }).click();
  await expect(page.getByText(/Baixa em .* Venda/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Mudar de lote" })).toHaveCount(0);

  await page.getByRole("button", { name: "Desfazer baixa" }).click();
  await page.getByLabel("Por que desfazer?").fill("E2E: baixa lançada por engano");
  await page.getByRole("button", { name: "Confirmar e trazer de volta" }).click();
  await expect(page.getByText(/Baixa em/)).toHaveCount(0);
});

test("senha provisória gerada pelo administrador", async ({ page }) => {
  await loginAsAdmin(page);
  await openArea(page, "Contas");
  const account = page.locator("li", { hasText: OPERATOR });
  await account.getByRole("button", { name: "Redefinir senha" }).click();
  await page.getByRole("button", { name: "Gerar senha provisória" }).click();

  const shown = page.locator(".temp-password code");
  await expect(shown).toHaveText(/^[a-z]+-[a-z]+-[a-z]+-\d\d$/);
  const temporary = (await shown.textContent()) ?? "";
  await page.getByRole("button", { name: "Já anotei" }).click();
  await expect(page.locator(".temp-password")).toHaveCount(0);
  await logout(page);

  // A senha anterior deixou de valer; a provisória só leva à troca.
  await login(page, OPERATOR, CHOSEN);
  await expect(page.getByRole("alert")).toContainText("E-mail ou senha inválidos.");

  await login(page, OPERATOR, temporary);
  await expect(page.getByRole("heading", { name: "Escolha uma senha nova" })).toBeVisible();
  await page.getByLabel("Senha atual").fill(temporary);
  await page.getByLabel("Nova senha").fill("cajarana no quintal");
  await page.getByRole("button", { name: "Trocar senha" }).click();
  await expect(page.getByRole("heading", { name: "Produção do dia" })).toBeVisible();
});
