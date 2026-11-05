import { expect, test, type APIRequestContext } from "@playwright/test";
import { runTag, openArea } from "./seed";

const TAG = runTag();
const PASSWORD = "pasto verde de muitos produtores";
const EMAIL = `produtor${TAG}@public-producers.test`;
const FARM = `Sítio independente ${TAG}`;
const SECOND = `Segunda fazenda ${TAG}`;
const MAIL = "http://localhost:8025";

async function verificationLink(request: APIRequestContext, email: string): Promise<string> {
  let id = "";
  await expect(async () => {
    const response = await request.get(`${MAIL}/api/v1/search?query=${encodeURIComponent(`to:${email}`)}`);
    expect(response.ok()).toBe(true);
    const body = await response.json();
    expect(body.messages.length).toBeGreaterThan(0);
    id = body.messages[0].ID;
  }).toPass({ timeout: 20_000 });
  const message = await (await request.get(`${MAIL}/api/v1/message/${id}`)).json();
  const link = /https?:\/\/\S+/.exec(message.Text);
  expect(link).not.toBeNull();
  return link![0];
}

test("produtor entra pelo cadastro, configura fazendas e importa seu próprio rebanho", async ({ page, request }) => {
  test.setTimeout(120_000);
  await page.goto("/");
  await page.getByRole("button", { name: "Sou produtor: criar conta" }).click();
  await page.getByLabel("Seu e-mail", { exact: true }).fill(EMAIL);
  await page.getByLabel("Seu nome ou nome da empresa").fill(`Produtor ${TAG}`);
  await page.getByLabel("Nome da primeira fazenda").fill(FARM);
  await page.getByLabel("Nova senha", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Criar conta de produtor", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("receberá um e-mail");
  const link = await verificationLink(request, EMAIL);
  await page.goto(link);
  await page.getByRole("button", { name: "Confirmar e-mail", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("E-mail confirmado");
  await page.getByRole("button", { name: "Voltar para entrar" }).click();
  await page.getByLabel("E-mail", { exact: true }).fill(EMAIL);
  await page.getByLabel("Senha", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await expect(page.getByLabel("Fazenda", { exact: true })).toContainText(FARM);
  await page.getByRole("button", { name: "Fazendas e equipe", exact: true }).click();
  await page.getByLabel("Lotes e grupos de manejo").fill("ordenha: Lote principal\nmanejo: Bezerreiro próprio");
  await page.getByRole("button", { name: "Salvar configuração" }).click();
  await expect(page.getByRole("navigation", { name: "Áreas" })).toBeVisible();
  await page.getByRole("button", { name: "Fazendas e equipe", exact: true }).click();
  await page.getByLabel("Arquivo de cadastro CSV").setInputFiles({ name: "cadastro.csv", mimeType: "text/csv", buffer: Buffer.from("brinco;nome;lote\n027;Mimosa do produtor;Lote principal\n028;Estrela do produtor;Lote principal") });
  await page.getByRole("button", { name: "Conferir cadastro", exact: true }).click();
  await expect(page.getByText(/2 novos animais/)).toBeVisible();
  await page.getByRole("button", { name: "Confirmar importação do cadastro" }).click();
  await expect(page.getByRole("status")).toContainText("Animais cadastrados");
  await page.getByLabel("Nome da nova fazenda").fill(SECOND);
  await page.getByRole("button", { name: "Criar fazenda", exact: true }).click();
  await expect(page.getByLabel("Fazenda", { exact: true }).locator("option")).toHaveCount(2);
  await page.getByLabel("Fazenda", { exact: true }).selectOption({ label: SECOND });
  await openArea(page, "Animais");
  await expect(page.getByRole("button", { name: /027 Mimosa do produtor/ })).toHaveCount(0);
  await page.getByLabel("Fazenda", { exact: true }).selectOption({ label: FARM });
  await openArea(page, "Animais");
  await expect(page.getByRole("button", { name: /027 Mimosa do produtor/ })).toBeVisible();
});
