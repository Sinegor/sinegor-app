import { defineConfig, devices } from "@playwright/test";
export default defineConfig({
  testDir: "./tests/browser",
  fullyParallel: true,
  workers: 2,
  reporter: "list",
  use: { baseURL: "http://localhost:3102", trace: "retain-on-failure" },
  webServer: {
    command: "npm run build && npm start",
    env: { HOST: "localhost", PORT: "3102" },
    url: "http://localhost:3102",
    reuseExistingServer: false,
    timeout: 30_000,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
