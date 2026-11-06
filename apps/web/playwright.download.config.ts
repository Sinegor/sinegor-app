import { defineConfig, devices } from "@playwright/test";
import config from "./playwright.config";

export default defineConfig(config, {
  testMatch: "agreement-download.spec.ts",
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "firefox", use: { ...devices["Desktop Firefox"] } },
  ],
});
