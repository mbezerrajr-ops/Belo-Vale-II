import { expect, test } from "@playwright/test";
import path from "node:path";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { uniqueFixtureCopy } from "./testFiles";

import { createMilkingCow, ensureAdminExists, ensureFarm, loginAsAdmin, openArea, runTag } from "./seed";

// No curral o sinal vai e volta. O que se lança sem sinal fica no celular,
// sobrevive a recarregar a página (ainda sem sinal) e chega ao servidor
// quando o sinal volta — sem digitar de novo.

const TAG = runTag();
let cow: { brinco: string; name: string };

test.beforeAll(() => {
  ensureAdminExists();
  ensureFarm();
  // Em LOTE 3, desde ontem.
  cow = createMilkingCow(`${TAG}O`);
});

test("lança sem sinal, recarrega sem sinal e o valor chega quando o sinal volta", async ({ page, context, browserName }) => {
  // No WebKit do Windows o service worker registra, controla a página e
  // guarda o app inteiro (conferido), mas o Playwright não consegue simular
  // a falta de rede numa navegação atendida por ele ("internal error" do
  // próprio Playwright). No iPhone isso se confere no teste de campo, com o
  // modo avião — ver docs/teste-de-campo-iphone.md.
  test.skip(browserName === "webkit", "Playwright/WebKit no Windows não simula rede ausente com service worker");
  test.setTimeout(120_000);
  await loginAsAdmin(page);
  // O app fica guardado no celular antes de o sinal cair.
  await page.evaluate(() => navigator.serviceWorker.ready.then(() => undefined));
  await openArea(page, "Produção");
  await page.getByRole("group", { name: "Lote de ordenha" }).getByRole("button", { name: "LOTE 3" }).click();
  const field = page.getByLabel(`Litros de ${cow.name}`);
  await expect(field).toBeVisible();

  await context.setOffline(true);
  await field.fill("23,5");
  await field.press("Tab");

  await expect(page.getByText(/guardado neste celular/i).first()).toBeVisible();
  await expect(page.getByRole("button", { name: /1 guardado/ })).toBeVisible();
  await expect(page.getByText(/sem sinal\. o que você lançar/i)).toBeVisible();

  // Recarregar sem sinal: o app abre, com a mesma pessoa, e o valor continua.
  await page.reload();
  await expect(page.getByRole("heading", { name: "Produção do dia" })).toBeVisible();
  await page.getByRole("group", { name: "Lote de ordenha" }).getByRole("button", { name: "LOTE 3" }).click();
  await expect(page.getByLabel(`Litros de ${cow.name}`)).toHaveValue("23,5");
  await expect(page.getByText(/folha guardada/i)).toBeVisible();

  // Uma tela nunca aberta também abre sem sinal: as partes do app que são
  // baixadas sob demanda já estavam guardadas no celular.
  await openArea(page, "Insumos");
  await expect(page.getByRole("heading", { name: "Insumos e dieta" })).toBeVisible();
  await openArea(page, "Produção");
  await page.getByRole("group", { name: "Lote de ordenha" }).getByRole("button", { name: "LOTE 3" }).click();

  // O sinal volta: vai sozinho.
  await context.setOffline(false);
  await expect(page.getByRole("button", { name: /guardado/ })).toHaveCount(0, { timeout: 45_000 });

  // E está no servidor: recarregar com sinal mostra o valor lançado.
  await page.reload();
  await page.getByRole("group", { name: "Lote de ordenha" }).getByRole("button", { name: "LOTE 3" }).click();
  await expect(page.getByLabel(`Litros de ${cow.name}`)).toHaveValue("23,5");
  await expect(page.getByText(/folha guardada/i)).toHaveCount(0);
});

test("fechar a página sem sinal conserva a sessão local e a fila até reabrir", async ({ page, context, browserName }) => {
  test.skip(browserName === "webkit", "Encerramento offline com service worker é conferido no aparelho físico");
  test.setTimeout(120_000);
  const fresh = createMilkingCow(`${runTag()}R`);
  await loginAsAdmin(page);
  await page.evaluate(() => navigator.serviceWorker.ready.then(() => undefined));
  await openArea(page, "Produção");
  await page.getByRole("group", { name: "Lote de ordenha" }).getByRole("button", { name: "LOTE 3" }).click();
  const field = page.getByLabel(`Litros de ${fresh.name}`);
  await expect(field).toBeVisible();
  await context.setOffline(true);
  await field.fill("19,5"); await field.press("Tab");
  await expect(page.getByText(/guardado neste celular/i).first()).toBeVisible();
  await expect(page.getByRole("button", { name: /^1 guardado$/ })).toBeVisible();
  await page.close();
  const reopened = await context.newPage();
  await reopened.goto("/producao");
  await expect(reopened.getByRole("heading", { name: "Produção do dia" })).toBeVisible();
  await reopened.getByRole("group", { name: "Lote de ordenha" }).getByRole("button", { name: "LOTE 3" }).click();
  await expect(reopened.getByLabel(`Litros de ${fresh.name}`)).toHaveValue("19,5");
  await context.setOffline(false);
  await expect(reopened.getByRole("button", { name: /guardado/ })).toHaveCount(0, { timeout: 45_000 });
  await reopened.reload();
  await reopened.getByRole("group", { name: "Lote de ordenha" }).getByRole("button", { name: "LOTE 3" }).click();
  await expect(reopened.getByLabel(`Litros de ${fresh.name}`)).toHaveValue("19,5");
});

test("foto da biblioteca conserva os bytes sem sinal e após fechar a página", async ({ page, context, browserName }) => {
  test.skip(browserName === "webkit", "Encerramento offline com service worker é conferido no aparelho físico");
  test.setTimeout(120_000);
  const file = uniqueFixtureCopy(path.resolve("e2e/fixtures/sheet.jpg"));
  const expectedHash = createHash("sha256").update(readFileSync(file)).digest("hex");
  await loginAsAdmin(page);
  await page.evaluate(() => navigator.serviceWorker.ready.then(() => undefined));
  await openArea(page, "Revisão");
  await page.getByRole("button", { name: "Enviar foto", exact: true }).click();
  await page.getByLabel("Foto da folha", { exact: true }).setInputFiles(file);
  await expect(page.getByAltText("Prévia da foto escolhida")).toBeVisible();
  await context.setOffline(true);
  await page.getByRole("button", { name: "Enviar", exact: true }).click();
  await expect(page.getByText(/a foto ficou guardada/i)).toBeVisible();
  await expect(page.getByRole("button", { name: /^1 guardado$/ })).toBeVisible();
  await page.close();
  const reopened = await context.newPage();
  await reopened.goto("/revisao");
  await expect(reopened.getByRole("button", { name: /^1 guardado$/ })).toBeVisible();
  const digest = await reopened.evaluate(async () => {
    const database = await new Promise<IDBDatabase>((resolve, reject) => { const request = indexedDB.open("belo-vale-outbox", 1); request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
    const items = await new Promise<Array<{ kind: string; blob: Blob }>>((resolve, reject) => { const request = database.transaction("items").objectStore("items").getAll(); request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
    const photo = items.find((item) => item.kind === "upload")!;
    const bytes = await crypto.subtle.digest("SHA-256", await photo.blob.arrayBuffer());
    return [...new Uint8Array(bytes)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
  });
  expect(digest).toBe(expectedHash);
  const sent = reopened.waitForResponse((response) => response.url().endsWith("/api/imports") && response.request().method() === "POST" && response.status() === 202);
  await context.setOffline(false);
  await sent;
  await expect(reopened.getByRole("button", { name: /guardado/ })).toHaveCount(0, { timeout: 45_000 });
});
