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
  await page.getByRole("button", { name: "Minha conta", exact: true }).first().click();
  await page.getByText("Configuração da minha fazenda", { exact: true }).click();
  await page.getByLabel("Lotes e grupos de manejo").fill("ordenha: Lote principal\nmanejo: Bezerreiro");
  await page.getByRole("button", { name: "Salvar configuração da fazenda" }).click();
  await expect(page.getByRole("status")).toContainText("Configuração da fazenda salva");
  await expect(page.getByText("Adicionar fazenda", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Importar cadastro de animais", { exact: true })).toHaveCount(0);
  await openArea(page, "Animais");
  await page.getByRole("button", { name: "Cadastrar animal", exact: true }).click();
  await page.getByLabel("Brinco (opcional)").fill("027");
  await page.getByLabel("Nome (opcional)").fill("Mimosa da Ana");
  await page.getByLabel("Lote ou grupo (opcional)").fill("Lote principal");
  await page.locator("form.create-animal").getByRole("button", { name: "Salvar animal", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Mimosa da Ana", exact: true })).toBeVisible();

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
