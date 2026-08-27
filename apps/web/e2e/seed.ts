import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

// This talks to the real Docker Compose stack via `docker compose exec`,
// the same way a human operator would seed data — not a mock, not a direct
// DB driver bypassing the running containers.
const currentDir = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(currentDir, "..", "..", "..");
const COMPOSE_FILE = path.join(REPO_ROOT, "infra", "docker-compose.yml");
const ENV_FILE = path.join(REPO_ROOT, "infra", ".env.e2e");

export const E2E_ADMIN_EMAIL = "e2e@belovale.test";
export const E2E_ADMIN_PASSWORD = "e2e-test-password-123";
export const E2E_FARM_NAME = "Fazenda E2E Playwright";
export const E2E_ANIMAL_NUMBER = "497";
export const E2E_ANIMAL_NAME = "PONTA CURTA";

function composeExec(args: string[], input?: string): string {
  return execFileSync(
    "docker",
    ["compose", "--env-file", ENV_FILE, "-f", COMPOSE_FILE, "exec", "-T", ...args],
    { encoding: "utf-8", input: input ?? "" },
  );
}

function psql(sql: string): string {
  // `-t` suppresses headers, but psql still appends a command tag like
  // "INSERT 0 1" on its own line after RETURNING's tuple output — only the
  // first line is the actual value.
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

export function ensureFarmAndAnimal(): { farmId: string } {
  let farmId = psql(`SELECT id FROM farms WHERE name = '${E2E_FARM_NAME}'`);
  if (!farmId) {
    farmId = psql(
      `INSERT INTO farms (id, name) VALUES (gen_random_uuid(), '${E2E_FARM_NAME}') RETURNING id`,
    );
  }

  const existingAnimal = psql(
    `SELECT 1 FROM animals WHERE farm_id = '${farmId}' AND identifier = '${E2E_ANIMAL_NUMBER}'`,
  );
  if (existingAnimal !== "1") {
    psql(
      `INSERT INTO animals (id, farm_id, identifier, name) VALUES (gen_random_uuid(), '${farmId}', '${E2E_ANIMAL_NUMBER}', '${E2E_ANIMAL_NAME}')`,
    );
  }

  return { farmId };
}
