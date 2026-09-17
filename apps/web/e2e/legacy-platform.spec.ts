import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { expect, test } from "@playwright/test";


const currentDir = path.dirname(fileURLToPath(import.meta.url));
const PLATFORM_HTML = path.resolve(
  currentDir,
  "../../../belo-vale-ii-projeto-completo/plataforma/platform_ATUAL_publicado.html",
);

function credentialsFromState(): { email: string; password: string } {
  const html = fs.readFileSync(PLATFORM_HTML, "utf-8");
  const match = html.match(
    /<script id="state-data" type="application\/json">([\s\S]*?)<\/script>/,
  );
  if (!match) throw new Error("state-data block not found in legacy platform");
  const state = JSON.parse(match[1]) as {
    usuarios: Array<{ email: string; senha: string }>;
  };
  const user = state.usuarios[0];
  if (!user) throw new Error("legacy platform has no login user");
  return { email: user.email, password: user.senha };
}

test("editing MIMOSA's lot does not mutate CAMBRAIA with the former duplicate id", async ({
  page,
}) => {
  const credentials = credentialsFromState();
  await page.addInitScript(() => {
    (window as Window & {
      claude?: { use: (namespace: string) => Promise<null> };
    }).claude = { use: async () => null };
  });

  await page.goto(pathToFileURL(PLATFORM_HTML).href);
  await page.getByLabel("E-mail").fill(credentials.email);
  await page.getByLabel("Senha").fill(credentials.password);
  await page.getByRole("button", { name: "Entrar" }).click();
  await page.getByRole("button", { name: "Vacas", exact: true }).click();

  const mimosa = page.getByRole("row").filter({ hasText: "MIMOSA" });
  const collidingCambraia = page
    .getByRole("row")
    .filter({ hasText: "CAMBRAIA" })
    .filter({ hasText: "570" });

  await mimosa.locator("select.lotesel").selectOption("LOTE 3");

  await expect(mimosa.locator("select.lotesel")).toHaveValue("LOTE 3");
  await expect(collidingCambraia.locator("select.lotesel")).not.toHaveValue(
    "LOTE 3",
  );
});
