import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { createMilkingCow, ensureAdminExists, ensureFarm, E2E_ADMIN_EMAIL, E2E_ADMIN_PASSWORD, login, runTag } from "./seed";

// Acessibilidade medida, não só olhada: o axe-core (a verificação que os
// leitores de tela e as normas WCAG usam de referência) roda em cada tela
// principal, nos dois temas. Falha com o que é grave ou crítico — contraste
// insuficiente, botão sem nome, campo sem rótulo, estrutura quebrada.

const TAG = runTag();
let cow: { brinco: string; name: string };

test.beforeAll(() => {
  ensureAdminExists();
  ensureFarm();
  cow = createMilkingCow(`${TAG}X`);
});

async function audit(page: Page, screen: string): Promise<string[]> {
  await page.waitForLoadState("networkidle");
  // O repouso: as animações de entrada mudam a opacidade e enganam o contraste.
  await page.waitForTimeout(400);
  const result = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  return result.violations
    .filter((violation) => violation.impact === "serious" || violation.impact === "critical")
    .map(
      (violation) =>
        `${screen}: ${violation.id} (${violation.impact}) — ${violation.help}\n    ` +
        violation.nodes
          .slice(0, 4)
          .map((node) => node.target.join(" "))
          .join("\n    "),
    );
}

async function go(page: Page, name: string): Promise<void> {
  const nav = page.getByRole("navigation", { name: "Áreas" });
  await nav.getByRole("button", { name: new RegExp(`^${name}`) }).first().click();
}

for (const theme of ["light", "dark"] as const) {
  test(`telas principais sem problema grave de acessibilidade (${theme})`, async ({ page }) => {
    test.setTimeout(120_000);
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.emulateMedia({ colorScheme: theme, reducedMotion: "reduce" });
    const problems: string[] = [];

    await page.goto("/");
    await expect(page.getByRole("button", { name: "Entrar" })).toBeVisible();
    problems.push(...(await audit(page, "login")));

    await login(page, E2E_ADMIN_EMAIL, E2E_ADMIN_PASSWORD);
    await expect(page.getByRole("navigation", { name: "Áreas" })).toBeVisible();
    problems.push(...(await audit(page, "painel")));

    for (const area of ["Produção", "Revisão", "Animais", "Insumos", "Medições", "Contas"]) {
      await go(page, area);
      problems.push(...(await audit(page, area.toLowerCase())));
    }

    await go(page, "Animais");
    await page.getByLabel("Brinco ou nome").fill(cow.name);
    await page.getByRole("button", { name: "Buscar", exact: true }).click();
    await page.getByRole("button", { name: new RegExp(cow.name) }).click();
    await expect(page.getByRole("heading", { name: cow.name })).toBeVisible();
    await page.getByRole("button", { name: /Mais ações/ }).click();
    problems.push(...(await audit(page, "ficha")));

    expect(problems, problems.join("\n")).toEqual([]);
  });
}

test("pelo teclado: o primeiro Tab oferece pular direto para a tela", async ({ page, browserName }) => {
  // O WebKit segue o Safari do Mac, em que Tab pula links; e o iPhone não
  // tem tecla Tab. O teclado vale para o computador, medido no Chrome.
  test.skip(browserName === "webkit", "Tab do Safari pula links; iPhone não tem teclado físico");
  await login(page, E2E_ADMIN_EMAIL, E2E_ADMIN_PASSWORD);
  await expect(page.getByRole("navigation", { name: "Áreas" })).toBeVisible();

  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", { name: "Pular para o conteúdo" });
  await expect(skip).toBeFocused();
  await expect(skip).toBeInViewport();

  await page.keyboard.press("Enter");
  await expect(page.locator("#conteudo")).toBeFocused();
});
