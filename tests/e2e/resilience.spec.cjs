const { test, expect, config } = require("./helpers.cjs");

test("CMS outage fails public SSR safely while independent FastAPI stays available", async ({
  request,
}) => {
  // This PID comes only from this runner's private ownership record.
  process.kill(config.service_pids.cms, "SIGSTOP");
  try {
    const response = await request.get("/publications/e2e-stable-article", {
      timeout: 12000,
    });
    expect(response.status()).toBe(503);
    expect((await request.get("/api/health/ready")).status()).toBe(200);
  } finally {
    process.kill(config.service_pids.cms, "SIGCONT");
  }
  await expect
    .poll(async () =>
      (await request.get("/publications/e2e-stable-article")).status(),
    )
    .toBe(200);
});
