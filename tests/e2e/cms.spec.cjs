const { test, expect, config, cms, runtimeErrors } = require("./helpers.cjs");

test("Strapi publication and media reach SSR without a frontend rebuild", async ({
  request,
  browser,
}) => {
  const draft = await cms({
    action: "create",
    data: {
      slug: "e2e-dynamic-article",
      title: "E2E новая публикация",
      summary: "Публичный анонс",
      sections: [{ text: "Полный текст <script>unsafe()</script>" }],
      seo: { title: "E2E SEO title", description: "E2E public description" },
    },
  });
  const route = "/publications/e2e-dynamic-article";
  await test.step("draft is hidden even with a public draft query", async () => {
    expect((await request.get(route)).status()).toBe(404);
    expect(
      (
        await request.get(
          `http://127.0.0.1:${config.ports.cms}/api/public-content/publications/e2e-dynamic-article?status=draft`,
        )
      ).status(),
    ).toBe(404);
  });
  await test.step("publish, draft edit and republish remain distinct", async () => {
    await cms({ action: "publish", id: draft.documentId });
    const response = await request.get(route);
    expect(response.status()).toBe(200);
    const html = await response.text();
    expect(html).toContain("E2E SEO title");
    expect(html).toContain(
      "Полный текст &lt;script&gt;unsafe()&lt;/script&gt;",
    );
    await cms({
      action: "update",
      id: draft.documentId,
      data: { title: "E2E обновлено без пересборки" },
    });
    expect(await (await request.get(route)).text()).not.toContain(
      "E2E обновлено без пересборки",
    );
    await cms({ action: "publish", id: draft.documentId });
    const context = await browser.newContext({
      javaScriptEnabled: false,
      baseURL: config.origin,
    });
    try {
      const page = await context.newPage();
      const errors = runtimeErrors(page);
      await page.goto(route);
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(
        "E2E обновлено без пересборки",
      );
      expect(errors.length).toBe(0);
    } finally {
      await context.close();
    }
    expect(await (await request.get("/publications")).text()).toContain(
      "e2e-dynamic-article",
    );
    await cms({ action: "unpublish", id: draft.documentId });
    expect((await request.get(route)).status()).toBe(404);
  });
  await test.step("real upload is served and public API stays read-only", async () => {
    const media = await cms({ action: "media" });
    expect(
      (
        await request.get(`http://127.0.0.1:${config.ports.cms}${media.url}`)
      ).status(),
    ).toBe(200);
    const page = await request.get("/pages/e2e-media");
    expect(page.status()).toBe(200);
    expect(await page.text()).toContain(media.url);
    expect([403, 404, 405]).toContain(
      (
        await request.post(
          `http://127.0.0.1:${config.ports.cms}/api/public-content/pages/home`,
          { data: { title: "forbidden" } },
        )
      ).status(),
    );
  });
});
