import { defineConfig, devices } from "@playwright/test";

// E2E assumes the real Docker Compose stack (db, redis, minio, api, worker,
// web) is already up — see docs/runbook-local.md. This test does not start
// or manage that stack itself, and it does not mock the API: every request
// goes through nginx to the real FastAPI service, real PostgreSQL, real
// Celery worker over real Redis. The only fake in the whole path is
// VISION_PROVIDER=fake (the substitutable adapter the architecture already
// provides for exactly this situation).
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  retries: 0,
  workers: 1,
  reporter: "list",
  // Margem para o executor de CI, mais lento e compartilhado que uma máquina
  // de desenvolvimento: sobretudo importa para a primeira asserção de cada
  // execução, que ainda paga o custo de conexões (banco, navegador) frias.
  expect: { timeout: 15_000 },
  // Maior que a maior janela de `toPass` usada nos specs (45s, para o worker
  // processar a ficha): o tempo do teste inteiro precisa sobrar folga além
  // da espera mais longa que ele contém, não apenas igualá-la.
  timeout: 90_000,
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:8080",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    // O navegador roda em UTC, como o runner do CI — e ao contrário da
    // máquina de quem desenvolve, em UTC−3. Sem isto, um "hoje" tirado do
    // fuso do aparelho passa aqui e quebra lá: foi o que aconteceu com o
    // lançamento de produção, recusado como data futura das 21h à meia-noite
    // de Brasília. O dia da fazenda é UTC−3 fixo, venha o aparelho de onde vier.
    timezoneId: "UTC",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
