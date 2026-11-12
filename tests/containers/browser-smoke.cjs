// Real browser checks against the local production Compose; no traces or credentials saved.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const cp = require("node:child_process");
const { chromium } = require("../../apps/web/node_modules/@playwright/test");
const root = path.resolve(__dirname, "../..");
const privateDir = path.resolve(process.env.SINEGOR_CONTAINER_CHECK_PRIVATE);
assert.ok(privateDir.startsWith(path.join(root, "storage") + path.sep));
const env = Object.fromEntries(
  fs
    .readFileSync(path.join(privateDir, "browser.env"), "utf8")
    .trim()
    .split("\n")
    .map((line) => {
      const split = line.indexOf("=");
      return [line.slice(0, split), line.slice(split + 1)];
    }),
);
assert.equal(env.LOCAL_CONTAINER_CHECK, "yes");
const origin = "https://localhost:18443";
let browser;
let stage = "launch";
(async () => {
  browser = await chromium.launch({ headless: true });
  const errors = [];
  const failedAssets = [];
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  context.setDefaultTimeout(15000);
  context.setDefaultNavigationTimeout(20000);
  const page = await context.newPage();
  page.on("pageerror", () => errors.push("pageerror"));
  page.on("requestfailed", (request) => {
    const url = new URL(request.url());
    if (url.origin === origin && /\.(css|js)$/.test(url.pathname))
      failedAssets.push("asset");
  });
  page.on("response", (response) => {
    const url = new URL(response.url());
    if (
      url.origin === origin &&
      /\.(css|js)$/.test(url.pathname) &&
      !response.ok()
    )
      failedAssets.push("asset");
  });
  stage = "public desktop/mobile";
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    for (const route of ["/", "/documents", "/auth/admin", "/auth/login"]) {
      stage = `public ${width}px ${route}: response`;
      const response = await page.goto(origin + route);
      assert.equal(response.status(), 200);
      stage = `public ${width}px ${route}: heading`;
      await page.locator("h1").first().waitFor();
      stage = `public ${width}px ${route}: stylesheet`;
      assert.ok(
        await page.evaluate(() =>
          [...document.styleSheets].some((sheet) => {
            try {
              return sheet.cssRules.length > 0;
            } catch {
              return false;
            }
          }),
        ),
      );
      assert.ok(
        await page.evaluate(() =>
          getComputedStyle(document.body).fontFamily.includes("Manrope"),
        ),
      );
      stage = `public ${width}px ${route}: viewport`;
      assert.ok(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      );
    }
  }
  assert.equal(errors.length, 0);
  assert.equal(failedAssets.length, 0);
  console.log(
    "PASS: production pages hydrate at desktop/mobile widths without page errors",
  );
  stage = "admin login";
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(origin + "/auth/admin");
  await page.getByLabel("Email администратора").fill(env.BROWSER_ADMIN_EMAIL);
  await page
    .getByLabel("Пароль", { exact: true })
    .fill(env.BROWSER_ADMIN_PASSWORD);
  const otp = cp
    .execFileSync(
      path.join(root, "apps/api/.venv/bin/python"),
      [
        "-c",
        "import os,pyotp;print(pyotp.TOTP(os.environ['BROWSER_ADMIN_TOTP']).now())",
      ],
      {
        env: { ...process.env, BROWSER_ADMIN_TOTP: env.BROWSER_ADMIN_TOTP },
        encoding: "utf8",
      },
    )
    .trim();
  await page.getByLabel("Одноразовый код").fill(otp);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  stage = "admin login redirect";
  await page.waitForURL(origin + "/admin/customers");
  const session = (await context.cookies()).find(
    (c) => c.name === "__Host-sinegor_session",
  );
  assert.ok(
    session?.secure && session.httpOnly && session.sameSite === "Strict",
  );
  await page.getByRole("button", { name: "Выйти", exact: true }).click();
  stage = "admin logout redirect";
  await page.waitForURL(origin + "/auth/admin");
  console.log(
    "PASS: browser password+TOTP login, Secure/HttpOnly/Strict session and logout",
  );
  stage = "customer login";
  await page.goto(
    origin + "/auth/magic-link#token=" + env.BROWSER_CUSTOMER_TOKEN,
  );
  await page
    .getByRole("button", { name: "Подтвердить вход", exact: true })
    .click();
  await page.waitForURL(origin + "/customer/orders");
  assert.equal(new URL(page.url()).hash, "");
  await page.getByRole("button", { name: "Выйти", exact: true }).click();
  await page.waitForURL(origin + "/auth/login");
  assert.equal(errors.length, 0);
  assert.equal(failedAssets.length, 0);
  await context.close();
  console.log(
    "PASS: browser magic-link login and logout; token fragment cleared",
  );
})()
  .catch((error) => {
    // Playwright messages can contain the magic-link URL. Emit only our fixed stage/type.
    console.error(`FAIL: browser smoke at ${stage} (${error.name})`);
    process.exitCode = 1;
  })
  .finally(async () => {
    if (browser) await browser.close();
  });
