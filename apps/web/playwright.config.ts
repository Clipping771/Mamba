import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests against a running stack (docker compose up) seeded with:
 *   docker compose exec -e BM_SEED_PASSWORD=... api blackmamba seed-demo
 * Run: E2E_PASSWORD=... pnpm test:e2e
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
