import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { runTag, openArea } from "./seed";

const PASSWORD = "pasto verde de muitos produtores";
async function register(page: Page, request: APIRequestContext, farm: string): Promise<void> {
  const email = `produtor${runTag()}@public-producers.test`;
  await page.goto("/");
  await page.getByRole("button", { name: "Sou produtor: criar conta" }).click();
  await page.getByLabel("Seu e-mail", { exact: true }).fill(email);
  await page.getByLabel("Seu nome ou nome da empresa").fill(`Produtor ${farm}`);
  await page.getByLabel("Nome da fazenda", { exact: true }).fill(farm);
  await page.getByLabel("Nova senha", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Criar conta de produtor", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("receberá um e-mail");
  const found = await request.get(`http://localhost:8025/api/v1/search?query=${encodeURIComponent(`to:${email}`)}`);
  const id = (await found.json()).messages[0].ID;
  const message = await (await request.get(`http://localhost:8025/api/v1/message/${id}`)).json();
  await page.goto(/https?:\/\/\S+/.exec(message.Text)![0]);
  await page.getByRole("button", { name: "Confirmar e-mail", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("E-mail confirmado");
  await page.getByRole("button", { name: "Voltar para entrar" }).click();
  await page.getByLabel("E-mail", { exact: true }).fill(email);
  await page.getByLabel("Senha", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await expect(page.getByRole("heading", { name: new RegExp(farm) }).first()).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Áreas" })).toBeVisible();
  await expect(page.getByLabel("Fazenda", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Fazendas e equipe" })).toHaveCount(0);
}

test("cada produtor entra direto na própria fazenda, sem seletor nem importação adicional", async ({ page, request, browser }) => {
  test.setTimeout(120_000);
  const farmA = `Sítio Ana ${runTag()}`;
  const farmB = `Sítio Bia ${runTag()}`;
  await register(page, request, farmA);
  await page.getByRole('link', { name: 'Configurar os lotes da fazenda', exact: true }).click();
  await expect(page).toHaveURL(/\/minha-conta\/fazenda$/);
  await expect(page.getByRole('button', { name: 'Adicionar lote ou grupo' })).toBeVisible();
  await page.getByRole('button', { name: 'Adicionar lote ou grupo' }).click();
  await page.locator('.farm-lot-row').last().getByLabel('Nome', { exact: true }).fill('Lote principal');
  await page.getByRole('button', { name: 'Adicionar lote ou grupo' }).click();
  await page.locator('.farm-lot-row').last().getByLabel('Nome', { exact: true }).fill('Bezerreiro');
  await page.locator('.farm-lot-row').last().getByLabel('Tipo').selectOption('management');
  await page.getByRole("button", { name: "Salvar configuração da fazenda" }).click();
  await expect(page.getByRole("status")).toContainText("Configuração da fazenda salva");
  await expect(page.getByText("Adicionar fazenda", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Importar cadastro de animais", { exact: true })).toHaveCount(0);
  await openArea(page, "Animais");
  await page.getByRole("button", { name: "Cadastrar animal", exact: true }).click();
  await page.getByLabel("Brinco (opcional)").fill("027");
  await page.locator("form.create-animal").getByLabel("Nome", { exact: true }).fill("Mimosa da Ana");
  await page.getByLabel("Lote ou grupo (opcional)").selectOption("Lote principal");
  await page.locator("form.create-animal").getByRole("button", { name: "Salvar animal", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Mimosa da Ana", exact: true })).toBeVisible();

  // O destino vem da configuração, com operação explícita e saída sem salvar.
  await page.getByRole('button', { name: 'Mudar de lote', exact: true }).click();
  await page.getByLabel('Novo lote ou grupo').selectOption('Bezerreiro');
  await expect(page.getByText(/Grupo de manejo: sem grupo → Bezerreiro/)).toBeVisible();
  await page.locator('.animal-detail form').getByRole('button', { name: 'Cancelar', exact: true }).click();
  await expect(page.getByLabel('Novo lote ou grupo')).toHaveCount(0);

  // Uma propriedade recém-criada consegue configurar o custo pelo navegador.
  await openArea(page, 'Insumos');
  await page.getByRole('button', { name: 'Novo insumo', exact: true }).click();
  await page.getByLabel('Nome', { exact: true }).fill('Silagem de teste');
  await page.getByLabel('Preço por kg (R$)', { exact: true }).fill('0.5');
  await page.getByRole('button', { name: 'Cadastrar insumo', exact: true }).click();
  await page.getByRole('button', { name: 'Definir dieta', exact: true }).click();
  await page.getByLabel('Quantidade diária para o lote inteiro (kg)').fill('60');
  await page.getByRole('button', { name: 'Salvar dieta', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('Dieta de Silagem de teste salva');
  await page.reload();
  await page.getByRole('button', { name: 'Definir dieta', exact: true }).click();
  await expect(page.getByLabel('Quantidade diária para o lote inteiro (kg)')).toHaveValue('60');

  await openArea(page, 'Produção');
  await page.getByRole('link', { name: 'Ler foto da folha', exact: true }).click();
  await expect(page).toHaveURL(/\/revisao\/foto$/);
  await expect(page.getByRole('heading', { name: 'Ler foto da folha', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Cancelar', exact: true }).click();
  await openArea(page, 'Histórico');
  await expect(page.getByText('Período consultado: todo o histórico disponível.')).toBeVisible();
  await openArea(page, 'Animais');
  await page.getByRole('button', { name: /027 Mimosa da Ana/ }).click();

  const otherContext = await browser.newContext({ baseURL: page.url().split("/").slice(0, 3).join("/") });
  try {
    const other = await otherContext.newPage();
    await register(other, request, farmB);
    await openArea(other, "Animais");
    await expect(other.getByRole("button", { name: /027 Mimosa da Ana/ })).toHaveCount(0);
    await page.reload();
    await expect(page.getByRole("heading", { name: "Mimosa da Ana", exact: true })).toBeVisible();
  } finally { await otherContext.close(); }
});
