const fs = require("node:fs");
const path = require("node:path");
const {
  defineConfig,
  devices,
} = require("../../apps/web/node_modules/@playwright/test");
const config = JSON.parse(fs.readFileSync(process.env.SINEGOR_E2E_CONFIG));
module.exports = defineConfig({
  testDir: __dirname,
  testMatch: "*.spec.cjs",
  workers: 1,
  retries: 0,
  timeout: 90000,
  expect: { timeout: 10000 },
  reporter: [[path.join(__dirname, "reporter.cjs")]],
  outputDir: path.join(config.private, "playwright"),
  use: {
    baseURL: config.origin,
    trace: "off",
    screenshot: "off",
    video: "off",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
