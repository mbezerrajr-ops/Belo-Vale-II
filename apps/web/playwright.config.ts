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
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:8080",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
