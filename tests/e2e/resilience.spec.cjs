const { test, expect, config } = require("./helpers.cjs");

test("CMS outage fails public SSR safely while independent FastAPI stays available", async ({
  request,
  page,
}) => {
  await page.goto("/publications/e2e-stable-article");
  const settings = page
    .getByRole("contentinfo")
    .getByRole("button", { name: "Настройки аналитики" });
  await expect(settings).toBeVisible();
  // This PID comes only from this runner's private ownership record.
  process.kill(config.service_pids.cms, "SIGSTOP");
  try {
    const response = await request.get("/publications/e2e-stable-article", {
      timeout: 12000,
    });
    expect(response.status()).toBe(503);
    expect((await request.get("/api/health/ready")).status()).toBe(200);
    // Login needs no CMS body: optional footer failure must preserve the shell.
    const login = await request.get("/auth/login", { timeout: 15000 });
    expect(login.status()).toBe(200);
    const footer = (await login.text()).match(
      /<footer\b[^>]*>[\s\S]*?<\/footer>/,
    )?.[0];
    expect(footer).toContain("SINEGOR");
    expect(footer).not.toMatch(/<a\b/);
    // Consent controls belong to public content routes, not authentication.
    // They remain usable on an already loaded content page during the outage.
    await settings.click();
    await expect(page.getByRole("dialog")).toBeVisible();
  } finally {
    process.kill(config.service_pids.cms, "SIGCONT");
  }
  await expect
    .poll(async () =>
      (await request.get("/publications/e2e-stable-article")).status(),
    )
    .toBe(200);
  expect((await request.get("/auth/login")).status()).toBe(200);
});
