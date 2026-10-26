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
    const cmsOrigin = `http://127.0.0.1:${config.ports.cms}`;
    await cms({
      action: "update",
      kind: "pages",
      id: media.id,
      data: {
        imageLayout: {
          position: "right",
          size: "small",
          alignment: "left",
          caption: "Подпись обложки",
        },
        sections: [
          { text: "Публичное медиа" },
          {
            text: "Раздел с иллюстрацией",
            image: media.mediaId,
            imageLayout: {
              position: "left",
              size: "medium",
              caption: "Подпись раздела",
            },
          },
        ],
      },
    });
    // Draft edits must not change the layout or sections of the published page.
    const before = await (
      await request.get(`${cmsOrigin}/api/public-content/pages/e2e-media`)
    ).json();
    expect(before.data.imageLayout).toBeNull();
    expect(before.data.sections).toHaveLength(1);
    await cms({ action: "publish", kind: "pages", id: media.id });
    const published = await (
      await request.get(`${cmsOrigin}/api/public-content/pages/e2e-media`)
    ).json();
    expect(published.data.image.url).toBe(media.url);
    expect(published.data.image.width).toBeGreaterThan(0);
    expect(published.data.imageLayout).toMatchObject({
      position: "right",
      size: "small",
      caption: "Подпись обложки",
    });
    expect(published.data.sections[0].text).toBe("Публичное медиа");
    expect(published.data.sections[1].image.url).toBe(media.url);
    expect(published.data.sections[1].imageLayout).toMatchObject({
      position: "left",
      size: "medium",
    });
    const updatedHtml = await (await request.get("/pages/e2e-media")).text();
    expect(updatedHtml).toContain("content-media--right");
    expect(updatedHtml).toContain("content-media--left");
    expect(updatedHtml).toContain("Публичное медиа");
    expect(updatedHtml).toContain("Подпись раздела");
    // The same optional components must persist for both other collection types.
    for (const kind of ["services", "publications"]) {
      const doc = await cms({
        action: "create",
        kind,
        data: {
          slug: "e2e-image-layout",
          title: "E2E единая компоновка",
          image: media.mediaId,
          imageLayout: { position: "left", size: "large" },
          sections: [
            {
              text: "Текст раздела",
              image: media.mediaId,
              imageLayout: { position: "right", size: "small" },
            },
          ],
        },
      });
      await cms({ action: "publish", kind, id: doc.documentId });
      const data = await (
        await request.get(
          `${cmsOrigin}/api/public-content/${kind}/e2e-image-layout`,
        )
      ).json();
      expect(data.data.imageLayout).toMatchObject({
        position: "left",
        size: "large",
      });
      expect(data.data.sections[0].image.url).toBe(media.url);
      const html = await (
        await request.get(`/${kind}/e2e-image-layout`)
      ).text();
      expect(html).toContain("content-media--left");
      expect(html).toContain("content-media--right");
      expect(html).toContain("Текст раздела");
    }
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

test("Content Manager enforces required image choices and saves root and section layouts", async ({
  page,
  request,
}) => {
  const origin = `http://localhost:${config.ports.cms}`;
  const legacy = await cms({ action: "media", slug: "e2e-cm-layout" });
  const documentPath = `/admin/content-manager/collection-types/api::page.page/${legacy.id}`;
  const publicPath = `${origin}/api/public-content/pages/e2e-cm-layout`;
  const errors = runtimeErrors(page);
  await page.route("**/*", (route) => {
    const hostname = new URL(route.request().url()).hostname;
    return ["localhost", "127.0.0.1"].includes(hostname)
      ? route.continue()
      : route.abort();
  });

  // Register a synthetic editor only in this run's disposable CMS database.
  await page.goto(`${origin}/admin`);
  await page.locator('input[name="firstname"]').fill("CMS");
  await page.locator('input[name="lastname"]').fill("Regression");
  await page.locator('input[name="email"]').fill("cms-editor@example.org");
  const password = `Aa1!${config.admin.password}`;
  await page.locator('input[name="password"]').fill(password);
  await page.locator('input[name="confirmPassword"]').fill(password);
  await page.getByRole("button", { name: "Let's start", exact: true }).click();
  await expect(
    page.getByRole("link", { name: "Content Manager", exact: true }),
  ).toBeVisible();

  async function saveAndPublish() {
    const save = page.getByRole("button", { name: "Save", exact: true });
    const [saved] = await Promise.all([
      page.waitForResponse(
        (r) =>
          r.request().method() === "PUT" &&
          r.url().includes(`/api::page.page/${legacy.id}`),
      ),
      save.click(),
    ]);
    expect(saved.status()).toBe(200);
    await expect(save).toBeDisabled();
    const [published] = await Promise.all([
      page.waitForResponse(
        (r) =>
          r.request().method() === "POST" &&
          r.url().includes(`/api::page.page/${legacy.id}/actions/publish`),
      ),
      page.getByRole("button", { name: "Publish", exact: true }).click(),
    ]);
    expect(published.status()).toBe(200);
  }

  const fields = [
    {
      name: "position",
      values: ["top", "left", "right"],
      initial: "top",
      chosen: "right",
    },
    {
      name: "size",
      values: ["small", "medium", "large", "full"],
      initial: "medium",
      chosen: "large",
    },
    {
      name: "alignment",
      values: ["left", "center", "right"],
      initial: "center",
      chosen: "left",
    },
  ];
  async function checkMenus(index) {
    for (const field of fields) {
      const select = page
        .getByRole("combobox", { name: new RegExp(`^${field.name}\\b`) })
        .nth(index);
      await expect(select).toBeVisible();
      await expect(select).toContainText(field.initial);
      await select.click();
      const empty = page.getByRole("option", {
        name: "Choose here",
        exact: true,
      });
      // Native Strapi sets hidden+disabled for required enums. Design-system 2.2.4
      // overrides [hidden] with display:flex, so visual removal remains an upstream
      // UI limitation; verify the required constraint without claiming it is hidden.
      await expect(empty).toBeDisabled();
      await expect(empty).toHaveAttribute("hidden", "");
      await expect(page.getByRole("option", { disabled: false })).toHaveText(
        field.values,
      );
      await page
        .getByRole("option", { name: field.chosen, exact: true })
        .click();
      await expect(select).toContainText(field.chosen);
    }
  }
  async function checkSavedValues(index) {
    for (const field of fields) {
      await expect(
        page
          .getByRole("combobox", { name: new RegExp(`^${field.name}\\b`) })
          .nth(index),
      ).toContainText(field.chosen);
    }
  }

  await test.step("a legacy material remains editable without an imageLayout component", async () => {
    await page.goto(origin + documentPath);
    await page
      .locator('input[name="title"]')
      .fill("E2E прежний материал после редактирования");
    await saveAndPublish();
    const { data } = await (await request.get(publicPath)).json();
    expect(data.title).toBe("E2E прежний материал после редактирования");
    expect(data.imageLayout).toBeNull();
    expect(data.image.url).toBe(legacy.url);
    expect(data.sections[0].text).toBe("Публичное медиа");
    expect(data.sections[0].imageLayout).toBeNull();
  });

  await test.step("all three root menus contain only valid choices, and selections persist", async () => {
    await page
      .getByRole("button", {
        name: "No entry yet. Click to add one.",
        exact: true,
      })
      .last()
      .click();
    await checkMenus(0);
    await saveAndPublish();
    await page.reload();
    await checkSavedValues(0);
    const { data } = await (await request.get(publicPath)).json();
    expect(data.imageLayout).toMatchObject({
      position: "right",
      size: "large",
      alignment: "left",
    });
    expect(data.image.url).toBe(legacy.url);
    expect(data.sections[0].text).toBe("Публичное медиа");
  });

  await test.step("the reused section component has the same menus and saves independently", async () => {
    await cms({
      action: "update",
      kind: "pages",
      id: legacy.id,
      data: {
        sections: [
          {
            text: "Публичное медиа",
            image: legacy.mediaId,
            imageLayout: {
              position: "top",
              size: "medium",
              alignment: "center",
            },
          },
        ],
      },
    });
    await page.goto(`${origin}${documentPath}?field=sections.0.text`);
    await expect(
      page.getByRole("combobox", { name: /^position\b/ }),
    ).toHaveCount(2);
    await checkMenus(0);
    await saveAndPublish();
    await page.reload();
    await checkSavedValues(0);
    await checkSavedValues(1);
    const { data } = await (await request.get(publicPath)).json();
    expect(data.sections[0].imageLayout).toMatchObject({
      position: "right",
      size: "large",
      alignment: "left",
    });
    expect(data.sections[0].image.url).toBe(legacy.url);
    expect(data.sections[0].text).toBe("Публичное медиа");
    expect(data.imageLayout).toMatchObject({
      position: "right",
      size: "large",
      alignment: "left",
    });
  });
  expect(errors).toEqual([]);
});
