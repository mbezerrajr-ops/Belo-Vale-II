import { expect, test, type Page } from "@playwright/test";

import { createMilkingCow, ensureAdminExists, ensureFarm, login, E2E_ADMIN_EMAIL, E2E_ADMIN_PASSWORD, runTag } from "./seed";

// O app é usado no aparelho, no curral. Esta auditoria mede — não olha — as
// regras que já quebraram uma vez e foram corrigidas:
//
// - nada rola de lado (a Revisão chegou a 351 px num celular de 320);
// - todo alvo de toque tem pelo menos 44 px (chips e "Anular" tinham 36–42);
// - campo de texto com letra de 16 px ou mais (abaixo, o iPhone amplia a tela);
// - o fim de cada tela passa da barra de baixo.
//
// Vale com qualquer dado: não confere números, só a forma.

const SIZES: Array<[number, number]> = [
  [320, 640],
  [390, 844],
  [844, 390],
];
const TAG = runTag();
let cow: { brinco: string; name: string };

test.beforeAll(() => {
  ensureAdminExists();
  ensureFarm();
  cow = createMilkingCow(`${TAG}M`);
});

async function measure(page: Page, screen: string): Promise<string[]> {
  await page.waitForLoadState("networkidle");
  // Espera o fim das animações de entrada: a medida é do repouso.
  await page.waitForTimeout(300);
  const found = await page.evaluate(() => {
    const out: string[] = [];
    const vw = document.documentElement.clientWidth;
    const name = (el: Element): string =>
      (el.getAttribute("aria-label") || (el as HTMLElement).innerText || el.tagName)
        .trim()
        .replace(/\s+/g, " ")
        .slice(0, 40);
    const shown = (el: Element): boolean => {
      const box = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return box.width > 0 && box.height > 0 && style.visibility !== "hidden";
    };
    if (document.documentElement.scrollWidth > vw + 1) {
      out.push(`rola de lado: ${document.documentElement.scrollWidth} px numa tela de ${vw}`);
    }
    document
      .querySelectorAll("button, a[href], input, select, textarea, summary")
      .forEach((el) => {
        if (!shown(el) || (el as HTMLInputElement).type === "hidden") return;
        const box = el.getBoundingClientRect();
        const isField = ["INPUT", "SELECT", "TEXTAREA"].includes(el.tagName);
        if (box.height < 44 || (!isField && box.width < 44)) {
          out.push(`alvo pequeno: "${name(el)}" ${Math.round(box.width)}×${Math.round(box.height)}`);
        }
        if (isField && parseFloat(getComputedStyle(el).fontSize) < 16) {
          out.push(`campo amplia no iPhone: "${name(el)}"`);
        }
      });
    const nav = document.querySelector(".areanav");
    if (nav && getComputedStyle(nav).position === "fixed") {
      window.scrollTo(0, document.documentElement.scrollHeight);
      const last = document.querySelector(".area")?.lastElementChild;
      const navTop = nav.getBoundingClientRect().top;
      if (last && last.getBoundingClientRect().bottom > navTop + 1) {
        out.push(`fim da tela atrás da barra: "${name(last)}"`);
      }
      window.scrollTo(0, 0);
    }
    return out;
  });
  return found.map((problem) => `${screen}: ${problem}`);
}

async function go(page: Page, name: string): Promise<void> {
  const nav = page.getByRole("navigation", { name: "Áreas" });
  const direct = nav.getByRole("button", { name: new RegExp(`^${name}`) });
  if ((await direct.count()) > 0 && (await direct.first().isVisible())) {
    await direct.first().click();
  } else {
    await nav.getByRole("button", { name: /^(Mais|Insumos|Medições|Contas|Minha conta)$/ }).click();
    await page.getByRole("group", { name: /mais áreas/i }).getByRole("button", { name: new RegExp(name) }).click();
  }
}

for (const [width, height] of SIZES) {
  test(`celular ${width}×${height}`, async ({ page }) => {
    test.setTimeout(120_000);
    await page.setViewportSize({ width, height });
    await page.emulateMedia({ reducedMotion: "reduce" });
    const problems: string[] = [];

    await page.goto("/");
    await expect(page.getByRole("button", { name: "Entrar" })).toBeVisible();
    problems.push(...(await measure(page, "login")));

    await login(page, E2E_ADMIN_EMAIL, E2E_ADMIN_PASSWORD);
    await expect(page.getByRole("navigation", { name: "Áreas" })).toBeVisible();
    problems.push(...(await measure(page, "painel")));

    await go(page, "Produção");
    problems.push(...(await measure(page, "produção")));
    await page.getByRole("button", { name: "Importar planilha/PDF" }).click();
    problems.push(...(await measure(page, "produção / importar")));
    await page.getByRole("button", { name: "Exportar" }).click();
    await expect(page.getByRole("button", { name: "Baixar planilha" })).toBeVisible();
    problems.push(...(await measure(page, "produção / exportar")));

    await go(page, "Revisão");
    problems.push(...(await measure(page, "revisão")));
    await page.getByRole("button", { name: "Ler foto da folha" }).click();
    problems.push(...(await measure(page, "revisão / enviar foto")));
    await page.getByRole("button", { name: "Cancelar" }).first().click();

    await go(page, "Animais");
    problems.push(...(await measure(page, "animais")));
    await page.getByLabel("Brinco ou nome").fill(cow.name);
    await page.getByRole("button", { name: "Buscar", exact: true }).click();
    await page.getByRole("button", { name: new RegExp(cow.name) }).click();
    await expect(page.getByRole("heading", { name: cow.name })).toBeVisible();
    problems.push(...(await measure(page, "ficha")));
    await page.getByRole("button", { name: /Mais ações/ }).click();
    problems.push(...(await measure(page, "ficha / mais ações")));

    await go(page, "Insumos");
    problems.push(...(await measure(page, "insumos")));
    await go(page, "Histórico");
    problems.push(...(await measure(page, "medições")));
    await go(page, "Equipe");
    await page.getByRole("button", { name: /Adicionar pessoa/ }).click();
    problems.push(...(await measure(page, "contas / nova conta")));
    await page.locator(".who .avatar").click();
    problems.push(...(await measure(page, "minha conta")));

    expect(problems, problems.join("\n")).toEqual([]);
  });
}
