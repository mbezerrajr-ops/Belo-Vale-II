import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, type Page } from "@playwright/test";

// Fala com a pilha Docker Compose real via `docker compose exec`, do jeito
// que uma pessoa operando o sistema faria — sem mock e sem driver de banco
// passando por fora dos contêineres.
const currentDir = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(currentDir, "..", "..", "..");
const COMPOSE_FILE = path.join(REPO_ROOT, "infra", "docker-compose.yml");
const ENV_FILE = path.join(REPO_ROOT, "infra", ".env.e2e");

export const E2E_ADMIN_EMAIL = "e2e@belovale.test";
export const E2E_ADMIN_PASSWORD = "curral de teste ponta a ponta";
export const E2E_FARM_NAME = "Fazenda E2E Playwright";
// O leitor falso de fotos e o transcritor falso devolvem sempre este animal,
// e a associação é só pelo brinco: o animal precisa ter exatamente este brinco.
export const E2E_ANIMAL_BRINCO = "497";
export const E2E_ANIMAL_NAME = "PONTA CURTA";

function composeExec(args: string[], input?: string): string {
  return execFileSync(
    "docker",
    ["compose", "--env-file", ENV_FILE, "-f", COMPOSE_FILE, "exec", "-T", ...args],
    { encoding: "utf-8", input: input ?? "" },
  );
}

function psql(sql: string): string {
  // `-t` tira o cabeçalho, mas o psql ainda acrescenta a etiqueta do comando
  // ("INSERT 0 1") numa linha própria depois do RETURNING: só a primeira
  // linha é o valor.
  const output = composeExec(["db", "psql", "-U", "ingestion", "-d", "ingestion", "-t", "-A", "-c", sql]);
  return (output.split("\n")[0] ?? "").trim();
}

export function ensureAdminExists(): void {
  const existing = psql(
    `SELECT 1 FROM users WHERE lower(email) = lower('${E2E_ADMIN_EMAIL}')`,
  );
  if (existing === "1") {
    return;
  }
  composeExec(
    ["api", "uv", "run", "--no-sync", "python", "-m", "app.core.bootstrap_admin", "--email", E2E_ADMIN_EMAIL],
    `${E2E_ADMIN_PASSWORD}\n${E2E_ADMIN_PASSWORD}\n`,
  );
}

export function ensureFarm(): string {
  let farmId = psql(`SELECT id FROM farms WHERE name = '${E2E_FARM_NAME}'`);
  if (!farmId) {
    farmId = psql(
      `INSERT INTO farms (id, name) VALUES (gen_random_uuid(), '${E2E_FARM_NAME}') RETURNING id`,
    );
  }
  let accountId = psql(`SELECT producer_account_id FROM farms WHERE id='${farmId}'`);
  if (!accountId) {
    accountId = psql(`INSERT INTO producer_accounts(name) VALUES ('Produtor E2E') RETURNING id`);
    psql(`UPDATE farms SET producer_account_id='${accountId}', lot_settings='[{"name":"LOTE 1","kind":"diet"},{"name":"LOTE 2","kind":"diet"},{"name":"LOTE 3","kind":"diet"}]'::jsonb WHERE id='${farmId}'`);
  }
  psql(`INSERT INTO producer_memberships(producer_account_id,user_id,role) SELECT '${accountId}',id,'owner' FROM users WHERE email='${E2E_ADMIN_EMAIL}' ON CONFLICT DO NOTHING`);
  psql(`INSERT INTO farm_memberships(farm_id,user_id,role,is_active) SELECT '${farmId}',id,role,is_active FROM users WHERE email LIKE '%@belovale.test' ON CONFLICT DO NOTHING`);
  return farmId;
}

/** O animal que o leitor falso "lê" na foto e na gravação. */
export function ensurePhotoSheetAnimal(): { farmId: string } {
  const farmId = ensureFarm();
  const existing = psql(
    `SELECT 1 FROM animals WHERE farm_id = '${farmId}' AND brinco = '${E2E_ANIMAL_BRINCO}'`,
  );
  if (existing !== "1") {
    psql(
      `INSERT INTO animals (id, farm_id, identifier, brinco, name) VALUES ` +
        `(gen_random_uuid(), '${farmId}', '${E2E_ANIMAL_BRINCO}', '${E2E_ANIMAL_BRINCO}', '${E2E_ANIMAL_NAME}')`,
    );
  }
  return { farmId };
}

/**
 * Uma vaca nova, única desta execução, em lote de ordenha.
 *
 * Postgres persiste entre execuções do E2E: reaproveitar a mesma vaca faria
 * a segunda execução esbarrar na produção lançada pela primeira.
 */
export function createMilkingCow(tag: string): { brinco: string; name: string } {
  const farmId = ensureFarm();
  const brinco = `E2E${tag}`;
  const name = `VACA ${tag}`;
  const animalId = psql(
    `INSERT INTO animals (id, farm_id, identifier, brinco, name, situacao, status) VALUES ` +
      `(gen_random_uuid(), '${farmId}', '${brinco}', '${brinco}', '${name}', 'Em lactação', 'Ativo') RETURNING id`,
  );
  psql(
    `INSERT INTO animal_lot_assignments (id, animal_id, lote, kind, valid_from, source) VALUES ` +
      `(gen_random_uuid(), '${animalId}', 'LOTE 3', 'diet', current_date - 1, 'manual')`,
  );
  return { brinco, name };
}

/** Sufixo único por execução: segundos desde a meia-noite + aleatório. */
export function runTag(): string {
  const now = new Date();
  const seconds = now.getHours() * 3600 + now.getMinutes() * 60 + now.getSeconds();
  return `${seconds}${Math.floor(Math.random() * 90 + 10)}`;
}

export async function login(page: Page, email: string, password: string): Promise<void> {
  await page.goto("/");
  await page.getByLabel("E-mail").fill(email);
  await page.getByLabel("Senha", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Entrar" }).click();
}

export async function loginAsAdmin(page: Page): Promise<void> {
  await login(page, E2E_ADMIN_EMAIL, E2E_ADMIN_PASSWORD);
  await expect(page.getByRole("navigation", { name: "Áreas" })).toBeVisible();
}

export async function logout(page: Page): Promise<void> {
  // No celular, Sair fica em Minha conta (no topo era fácil de tocar sem
  // querer); no computador, no topo.
  const sair = page.getByRole("button", { name: "Sair" }).filter({ visible: true }).first();
  if ((await sair.count()) === 0) await page.locator(".who .avatar").click();
  await page.getByRole("button", { name: "Sair" }).filter({ visible: true }).first().click();
  await expect(page.getByRole("button", { name: "Entrar" })).toBeVisible();
}

export async function openArea(page: Page, name: RegExp | string): Promise<void> {
  // A barra muda depois do primeiro desenho (a contagem da revisão chega
  // depois); um clique no meio desse rearranjo pode cair no vizinho. Clica
  // de novo até a área ficar marcada como atual.
  //
  // No celular (o perfil iPhone), só quatro áreas ficam na barra: as outras
  // estão dentro de "Mais". O botão visível é o que vale — os da barra de
  // computador existem escondidos.
  const nav = page.getByRole("navigation", { name: "Áreas" });
  const button = nav.getByRole("button", { name }).filter({ visible: true }).first();
  await expect(async () => {
    if ((await button.count()) > 0) {
      await button.click();
    } else {
      await nav.getByRole("button", { name: /^(Mais|Insumos|Medições|Contas|Minha conta)$/ }).click();
      await page.getByRole("group", { name: /mais áreas/i }).getByRole("button", { name }).click();
    }
    await expect(button).toHaveAttribute("aria-current", "true", { timeout: 2_000 });
  }).toPass({ timeout: 15_000 });
}

/**
 * Manda uma leitura para a caixa de revisão pelo comando de carga, como os
 * leitores de foto e áudio farão. A extração vai pela entrada padrão.
 */
export function loadProposals(extraction: object, label: string): void {
  composeExec(
    [
      "api", "uv", "run", "--no-sync", "python", "-m", "app.core.load_proposals",
      "--email", E2E_ADMIN_EMAIL, "--file", "-", "--label", label, "--kind", "photo",
      "--farm-id", ensureFarm(),
    ],
    JSON.stringify(extraction),
  );
}

/** `aaaa-mm-dd` de alguns dias atrás. Nunca "hoje": o executor do CI roda em
 * UTC, e depois das 21h no Nordeste o "hoje" dele já é amanhã na fazenda. */
export function daysAgo(days: number): string {
  const moment = new Date(Date.now() - days * 24 * 60 * 60 * 1000);
  return moment.toISOString().slice(0, 10);
}
