const paragraph = (text) => [
  { type: "paragraph", children: [{ type: "text", text }] },
];
const { test, expect, config, cms, runtimeErrors } = require("./helpers.cjs");

test("public documents follow Strapi draft, publication, revision and withdrawal", async ({
  request,
  browser,
}) => {
  const route = "/documents/privacy-policy";
  const pdf = await cms({ action: "pdf", kind: "documents" });
  const draft = await cms({
    action: "create",
    kind: "documents",
    data: {
      slug: "privacy-policy",
      title: "E2E тестовый документ",
      body: paragraph("E2E синтетический текст <script>unsafe()</script>"),
      revisedOn: "2026-11-02",
      pdf: pdf.mediaId,
      seo: { title: "E2E document SEO", description: "E2E description" },
    },
  });
  const html = async () => (await request.get(route)).text();
  const sitemap = async () => (await request.get("/sitemap.xml")).text();
  expect((await request.get(route)).status()).toBe(200);
  expect((await html()).split("</head>")[0]).toContain(
    'name="robots" content="noindex, follow"',
  );
  expect(await html()).toContain("Документ готовится к публикации");
  expect(await sitemap()).not.toContain(`${config.origin}${route}`);
  expect(
    (
      await request.get(
        `http://127.0.0.1:${config.ports.cms}/api/public-content/documents/privacy-policy?status=draft`,
      )
    ).status(),
  ).toBe(404);
  await cms({ action: "publish", kind: "documents", id: draft.documentId });
  expect(await html()).toContain("E2E document SEO");
  expect(await html()).toContain(pdf.url);
  const attachment = await request.get(
    `http://127.0.0.1:${config.ports.cms}${pdf.url}`,
  );
  expect(attachment.status()).toBe(200);
  expect(attachment.headers()["content-type"]).toContain("application/pdf");
  expect(await html()).toContain(
    "E2E синтетический текст &lt;script&gt;unsafe()&lt;/script&gt;",
  );
  expect((await html()).split("</head>")[0]).not.toContain('name="robots"');
  expect(await sitemap()).toContain(`${config.origin}${route}`);
  const context = await browser.newContext({
    javaScriptEnabled: false,
    baseURL: config.origin,
  });
  try {
    const page = await context.newPage();
    await page.goto(route);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      "E2E тестовый документ",
    );
    await expect(page.locator("time")).toHaveAttribute(
      "datetime",
      "2026-11-02",
    );
    await expect(page.locator("main")).toContainText("E2E синтетический текст");
  } finally {
    await context.close();
  }
  await cms({
    action: "update",
    kind: "documents",
    id: draft.documentId,
    data: { title: "E2E новая редакция" },
  });
  expect(await html()).not.toContain("E2E новая редакция");
  await cms({ action: "publish", kind: "documents", id: draft.documentId });
  expect(await html()).toContain("E2E новая редакция");
  await cms({ action: "unpublish", kind: "documents", id: draft.documentId });
  expect(await html()).toContain("Документ готовится к публикации");
  expect(await sitemap()).not.toContain(`${config.origin}${route}`);
});

test("document CMS outages return 503 with noindex and preserve public navigation", async ({
  request,
  page,
}) => {
  process.kill(config.service_pids.cms, "SIGSTOP");
  try {
    for (const path of ["/documents", "/documents/service-rules"]) {
      const response = await request.get(path, { timeout: 12000 });
      expect(response.status()).toBe(503);
      expect(response.headers()["cache-control"]).toBe("no-store");
      const html = await response.text();
      expect(html).toContain("Документы временно недоступны");
      expect(html.split("</head>")[0]).toContain(
        'name="robots" content="noindex, follow"',
      );
      expect(html).not.toContain("Документ готовится к публикации");
    }
    await page.goto("/documents/service-rules");
    await expect(page.getByRole("contentinfo")).toBeVisible();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      "Документы временно недоступны",
    );
  } finally {
    process.kill(config.service_pids.cms, "SIGCONT");
  }
  expect((await request.get("/documents/service-rules")).status()).toBe(200);
});

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
      sections: [
        { general: paragraph("Полный текст <script>unsafe()</script>") },
      ],
      seo: { title: "E2E SEO title", description: "E2E public description" },
    },
  });
  const route = "/publications/e2e-dynamic-article";
  const sitemap = async () => {
    const response = await request.get("/sitemap.xml");
    expect(response.status()).toBe(200);
    expect(response.headers()["content-type"]).toContain("application/xml");
    return response.text();
  };
  await test.step("draft is hidden even with a public draft query", async () => {
    expect((await request.get(route)).status()).toBe(404);
    expect(await sitemap()).not.toContain(`${config.origin}${route}`);
    const robots = await request.get("/robots.txt");
    expect(robots.status()).toBe(200);
    expect(await robots.text()).toContain(
      `Sitemap: ${config.origin}/sitemap.xml`,
    );
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
    expect(await sitemap()).toContain(`<loc>${config.origin}${route}</loc>`);
    expect(await (await request.get("/publications")).text()).toContain(
      `href="${route}"`,
    );
    await cms({
      action: "update",
      id: draft.documentId,
      data: {
        title: "E2E обновлено без пересборки",
        seo: { title: "E2E SEO title", noindex: true },
      },
    });
    expect(await (await request.get(route)).text()).not.toContain(
      "E2E обновлено без пересборки",
    );
    expect(await sitemap()).toContain(`<loc>${config.origin}${route}</loc>`);
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
    expect(await sitemap()).not.toContain(`${config.origin}${route}`);
    expect(
      (await (await request.get(route)).text()).split("</head>")[0],
    ).toContain('name="robots" content="noindex, follow"');
    await cms({
      action: "update",
      id: draft.documentId,
      data: { seo: { noindex: false } },
    });
    await cms({ action: "publish", id: draft.documentId });
    expect(await sitemap()).toContain(`<loc>${config.origin}${route}</loc>`);
    await cms({ action: "unpublish", id: draft.documentId });
    expect((await request.get(route)).status()).toBe(404);
    expect(await sitemap()).not.toContain(`${config.origin}${route}`);
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
    expect(await sitemap()).toContain(
      `<loc>${config.origin}/pages/e2e-media</loc>`,
    );
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
          { general: paragraph("Публичное медиа") },
          {
            general: paragraph("Раздел с иллюстрацией"),
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
    expect(published.data.sections[0].general[0].children[0].text).toBe(
      "Публичное медиа",
    );
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
              general: paragraph("Текст раздела"),
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
      expect(await sitemap()).toContain(
        `<loc>${config.origin}/${kind}/e2e-image-layout</loc>`,
      );
      await cms({ action: "unpublish", kind, id: doc.documentId });
      expect(await sitemap()).not.toContain(
        `${config.origin}/${kind}/e2e-image-layout`,
      );
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
  await test.step("published SEO pages appear in managed SSR links without entering the main menu", async () => {
    const guide = await cms({
      action: "create",
      kind: "pages",
      data: {
        slug: "e2e-context-guide",
        title: "Практическое руководство",
        sections: [],
        linkSection: "technical",
        linkOrder: 2,
      },
    });
    const link = 'href="/pages/e2e-context-guide"';
    expect(
      await (await request.get("/services/technical")).text(),
    ).not.toContain(link);
    await cms({ action: "publish", kind: "pages", id: guide.documentId });
    const html = await (await request.get("/services/technical")).text();
    expect(html).toContain(link);
    expect(html.split("</header>")[0]).not.toContain(link);
    expect(await (await request.get("/publications")).text()).not.toContain(
      link,
    );
    await cms({
      action: "update",
      kind: "pages",
      id: guide.documentId,
      data: { linkSection: "about", linkOrder: 1 },
    });
    expect(await (await request.get("/services/technical")).text()).toContain(
      link,
    );
    expect(await (await request.get("/about")).text()).not.toContain(link);
    await cms({ action: "publish", kind: "pages", id: guide.documentId });
    expect(
      await (await request.get("/services/technical")).text(),
    ).not.toContain(link);
    const context = await browser.newContext({
      javaScriptEnabled: false,
      baseURL: config.origin,
    });
    try {
      const page = await context.newPage();
      await page.goto("/about");
      await page
        .getByRole("navigation", { name: "Материалы по теме" })
        .getByRole("link", { name: "Практическое руководство" })
        .click();
      await expect(page).toHaveURL(`${config.origin}/pages/e2e-context-guide`);
      await expect(page.locator('head link[rel="canonical"]')).toHaveAttribute(
        "href",
        `${config.origin}/pages/e2e-context-guide`,
      );
    } finally {
      await context.close();
    }
    await cms({
      action: "update",
      kind: "pages",
      id: guide.documentId,
      data: { seo: { noindex: true } },
    });
    await cms({ action: "publish", kind: "pages", id: guide.documentId });
    expect(await (await request.get("/about")).text()).not.toContain(link);
    await cms({ action: "unpublish", kind: "pages", id: guide.documentId });
    expect(await (await request.get("/about")).text()).not.toContain(link);
    const underscore = await cms({
      action: "create",
      kind: "pages",
      data: {
        slug: "_",
        title: "Материал с допустимым slug",
        sections: [],
      },
    });
    await cms({ action: "publish", kind: "pages", id: underscore.documentId });
    const jsContext = await browser.newContext({ baseURL: config.origin });
    try {
      const page = await jsContext.newPage();
      await page.goto("/publications");
      await page
        .getByRole("navigation", { name: "Материалы по теме" })
        .getByRole("link", { name: "Материал с допустимым slug" })
        .click();
      await expect(page).toHaveURL(`${config.origin}/pages/%5F`);
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(
        "Материал с допустимым slug",
      );
      await expect(page.locator('head link[rel="canonical"]')).toHaveAttribute(
        "href",
        `${config.origin}/pages/%5F`,
      );
    } finally {
      await jsContext.close();
    }
  });
  await test.step("real catalogue pagination preserves distinct canonical pages and rejects missing ones", async () => {
    // One stable published article was seeded by the isolated CMS fixture.
    const articles = [];
    for (let i = 0; i < 25; i++) {
      const article = await cms({
        action: "create",
        data: {
          slug: `e2e-pagination-${i}`,
          title: `Pagination ${i}`,
          sections: [],
        },
      });
      await cms({ action: "publish", id: article.documentId });
      articles.push(article);
    }
    const context = await browser.newContext({
      javaScriptEnabled: false,
      baseURL: config.origin,
    });
    try {
      const page = await context.newPage();
      await page.goto("/publications");
      await expect(page.locator(".public-grid > .card")).toHaveCount(25);
      await page.getByRole("link", { name: "Далее", exact: true }).click();
      await expect(page).toHaveURL(`${config.origin}/publications?offset=25`);
      await expect(page.locator(".public-grid > .card")).toHaveCount(1);
      await expect(page.locator('head link[rel="canonical"]')).toHaveAttribute(
        "href",
        `${config.origin}/publications?offset=25`,
      );
      await expect(
        page.getByRole("link", { name: "Далее", exact: true }),
      ).toHaveCount(0);
      await page.getByRole("link", { name: "Назад", exact: true }).click();
      await expect(page).toHaveURL(`${config.origin}/publications`);
      await cms({ action: "unpublish", id: articles[0].documentId });
      const missing = await request.get("/publications?offset=25");
      expect(missing.status()).toBe(404);
      expect((await missing.text()).split("</head>")[0]).not.toContain(
        'rel="canonical"',
      );
      await page.reload();
      await expect(
        page.getByRole("link", { name: "Далее", exact: true }),
      ).toHaveCount(0);
      expect(await sitemap()).not.toContain(
        `${config.origin}/publications?offset=25`,
      );
    } finally {
      await context.close();
    }
    for (const offset of ["1", "999999", "1000000"]) {
      expect(
        (await request.get(`/publications?offset=${offset}`)).status(),
      ).toBe(404);
    }
    for (const query of ["offset=-25", "offset=bad", "offset=0&unused=1"]) {
      const response = await request.get(`/publications?${query}`, {
        maxRedirects: 0,
      });
      expect(response.status()).toBe(308);
      expect(response.headers().location).toBe(`${config.origin}/publications`);
    }
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
    expect(data.sections[0].general[0].children[0].text).toBe(
      "Публичное медиа",
    );
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
    expect(data.sections[0].general[0].children[0].text).toBe(
      "Публичное медиа",
    );
  });

  await test.step("the reused section component has the same menus and saves independently", async () => {
    await cms({
      action: "update",
      kind: "pages",
      id: legacy.id,
      data: {
        sections: [
          {
            general: paragraph("Публичное медиа"),
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
    await page.goto(`${origin}${documentPath}?field=sections.0.general`);
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
    expect(data.sections[0].general[0].children[0].text).toBe(
      "Публичное медиа",
    );
    expect(data.imageLayout).toMatchObject({
      position: "right",
      size: "large",
      alignment: "left",
    });
  });
  expect(errors).toEqual([]);
});
