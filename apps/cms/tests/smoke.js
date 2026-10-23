// Run against this project's CMS database, with a built frontend on WEB_TEST_ORIGIN.
require("dotenv").config();
const assert = require("node:assert/strict");
const { createStrapi } = require("@strapi/strapi");
const fs = require("node:fs");
const path = require("node:path");
async function main() {
  const app = await createStrapi().load();
  const created = [];
  let uploaded;
  try {
    await app.start();
    const origin = `http://127.0.0.1:${process.env.PORT || 1337}`;
    const web = process.env.WEB_TEST_ORIGIN;
    assert.ok(
      web,
      "WEB_TEST_ORIGIN must point to a running built frontend with CMS_ORIGIN configured",
    );
    const slug = `smoke-${Date.now()}`;
    const docs = app.documents("api::publication.publication");
    const draft = await docs.create({
      status: "draft",
      data: {
        slug,
        title: "Проверка публикации",
        summary: "Тестовый материал",
        sections: [{ text: "Полный текст <script>test</script>" }],
        seo: {
          title: "Проверка SEO",
          description: "Описание для поисковой системы",
        },
      },
    });
    created.push(["api::publication.publication", draft.documentId]);
    assert.equal(
      (
        await fetch(
          `${origin}/api/public-content/publications/${slug}?status=draft`,
        )
      ).status,
      404,
    );
    assert.equal((await fetch(`${web}/publications/${slug}`)).status, 404);
    await docs.publish({ documentId: draft.documentId });
    let response = await fetch(`${web}/publications/${slug}`);
    assert.equal(response.status, 200);
    let html = await response.text();
    assert.ok(html.includes("Полный текст &lt;script&gt;test&lt;/script&gt;"));
    assert.ok(html.includes("Проверка SEO"));
    await docs.update({
      documentId: draft.documentId,
      data: { title: "Обновлено без пересборки" },
    });
    html = await (await fetch(`${web}/publications/${slug}`)).text();
    assert.ok(!html.includes("Обновлено без пересборки"));
    await docs.publish({ documentId: draft.documentId });
    html = await (await fetch(`${web}/publications/${slug}`)).text();
    assert.ok(html.includes("Обновлено без пересборки"));
    assert.ok(
      (await (await fetch(`${web}/publications`)).text()).includes(slug),
    );
    const filePath = path.resolve(
      "../web/public/media/sinegor-lab-preview.jpg",
    );
    [uploaded] = await app
      .plugin("upload")
      .service("upload")
      .upload({
        data: {},
        files: {
          filepath: filePath,
          originalFilename: "smoke.jpg",
          mimetype: "image/jpeg",
          size: fs.statSync(filePath).size,
        },
      });
    const pages = app.documents("api::page.page");
    const page = await pages.create({
      status: "published",
      data: {
        slug,
        title: "Проверка страницы",
        sections: [{ text: "Контент из CMS" }],
        image: uploaded.id,
      },
    });
    created.push(["api::page.page", page.documentId]);
    response = await fetch(`${web}/pages/${slug}`);
    assert.equal(response.status, 200);
    assert.ok((await response.text()).includes(uploaded.url));
    assert.equal((await fetch(new URL(uploaded.url, origin))).status, 200);
    assert.notEqual(
      (
        await fetch(`${origin}/api/public-content/pages/${slug}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ data: { title: "forbidden" } }),
        })
      ).status,
      200,
    );
    if (process.env.CMS_SCREENSHOTS === "1") {
      const { chromium } = require("../../web/node_modules/playwright");
      const browser = await chromium.launch({ headless: true });
      try {
        for (const width of [1440, 390]) {
          const browserPage = await browser.newPage({
            viewport: { width, height: 900 },
          });
          for (const route of [
            `/pages/${slug}`,
            `/publications/${slug}`,
            "/publications",
          ]) {
            await browserPage.goto(`${web}${route}`);
            assert.ok(await browserPage.locator("h1").isVisible());
            assert.ok(
              (await browserPage.evaluate(
                () => document.documentElement.scrollWidth,
              )) <= width,
            );
            await browserPage.screenshot({
              path: `/tmp/sinegor-f5/${width}-${route.split("/")[1]}-${route.split("/")[2] ? "detail" : "list"}.png`,
              fullPage: true,
            });
          }
          await browserPage.close();
        }
      } finally {
        await browser.close();
      }
    }
    console.log(
      "PASS: drafts hidden, safe SSR, SEO, publish/update without rebuild, catalogue, dynamic pages, upload delivery, read-only public API",
    );
  } finally {
    for (const [uid, documentId] of created.reverse())
      await app.documents(uid).delete({ documentId });
    if (uploaded) await app.plugin("upload").service("upload").remove(uploaded);
    await app.destroy();
  }
}
main().catch((error) => {
  console.error(
    "CMS smoke failed:",
    error.name,
    error.code || "assertion/configuration",
    error.stack?.split("\n").slice(1, 4).join("\n"),
  );
  process.exitCode = 1;
});
