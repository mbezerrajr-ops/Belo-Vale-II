import { expect, test } from "@playwright/test";

import { ensureAdminExists, ensurePhotoSheetAnimal, loginAsAdmin, openArea } from "./seed";

// Gravar a ordenha dentro do próprio app, de ponta a ponta, na pilha real.
//
// O microfone é o falso do Chromium (um tom contínuo), com a permissão já
// dada. O que ele grava sai no formato de verdade do navegador — é isso que
// passa pela porta de entrada do servidor e pelo worker —, e o transcritor
// falso ouve a frase de sempre ("A 497 deu 18 litros de manhã e 15 à tarde").
//
// Num arquivo próprio: as opções de abertura do navegador valem para o
// arquivo inteiro.
test.use({
  launchOptions: {
    args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"],
  },
  permissions: ["microphone"],
});

test.beforeAll(() => {
  ensureAdminExists();
  ensurePhotoSheetAnimal();
});

test("grava, ouve, envia, e a proposta chega sozinha", async ({ page, browserName }) => {
  // O microfone falso (--use-fake-device-for-media-stream) só existe no
  // Chromium. No iPhone, o gravador se confere no teste de campo.
  test.skip(browserName === "webkit", "microfone falso só existe no Chromium");
  await loginAsAdmin(page);
  await openArea(page, /Revisão/);

  await page.getByRole("button", { name: /enviar [áa]udio/i }).click();
  await page.getByRole("button", { name: /gravar agora/i }).click();
  await expect(page.getByText(/gravando 0:0/i)).toBeVisible();
  // Um pouco de "fala" (tom, aqui): o bastante para haver o que enviar.
  await page.waitForTimeout(1_500);
  await page.getByRole("button", { name: "Parar", exact: true }).click();

  await expect(page.getByLabel(/ouvir o que foi gravado/i)).toBeVisible();
  await page.getByRole("button", { name: /Enviar (áudio )?para leitura/,  exact: true }).click();

  // Sem apertar "Atualizar": a tela acompanha a leitura até o fim.
  await expect(page.getByText(/1 registro da grava[çc][ãa]o.*aguardando conferência/i)).toBeVisible({
    timeout: 45_000,
  });
});
