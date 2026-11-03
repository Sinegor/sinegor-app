import { test, expect } from "@playwright/test";

test("nonexistent publication pages return 404 without a canonical", async ({
  request,
}) => {
  for (const offset of ["25", "999999", "1000000"]) {
    const response = await request.get(`/publications?offset=${offset}`, {
      maxRedirects: 0,
    });
    expect(response.status(), offset).toBe(404);
    expect((await response.text()).split("</head>")[0]).not.toContain(
      'rel="canonical"',
    );
  }
});

test("discovery files serve canonical standalone URLs and a public sitemap reference", async ({
  request,
}) => {
  const response = await request.get("/sitemap.xml");
  expect(response.status()).toBe(200);
  expect(response.headers()["content-type"]).toContain("application/xml");
  const xml = await response.text();
  expect(xml).toContain('xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"');
  for (const path of [
    "/",
    "/about",
    "/contacts",
    "/documents",
    "/publications",
    "/services/ai-analysis",
    "/services/technical",
  ])
    expect(xml).toContain(`<loc>http://localhost:3102${path}</loc>`);
  expect(xml.match(/<loc>/g)).toHaveLength(7);
  const robots = await request.get("/robots.txt");
  expect(robots.status()).toBe(200);
  expect(robots.headers()["content-type"]).toContain("text/plain");
  expect(await robots.text()).toContain(
    "Sitemap: http://localhost:3102/sitemap.xml",
  );
});

test("public duplicates redirect permanently and canonical is present once in SSR HTML", async ({
  request,
}) => {
  for (const path of ["/about/", "/ABOUT", "/pages/about"]) {
    const response = await request.get(path, { maxRedirects: 0 });
    expect(response.status()).toBe(308);
    expect(new URL(response.headers().location, response.url()).pathname).toBe(
      "/about",
    );
  }
  const response = await request.get("/about");
  expect(response.status()).toBe(200);
  const head = (await response.text()).split("</head>")[0];
  const links = head.match(/<link\b[^>]*rel="canonical"[^>]*>/g) || [];
  expect(links).toHaveLength(1);
  expect(links[0]).toContain('href="http://localhost:3102/about"');
});

test("public pages render server-side and unknown publications return 404", async ({
  request,
}) => {
  for (const [path, title] of [
    ["/", "Исследование юридических документов"],
    ["/services/ai-analysis", "ИИ-анализ документов"],
    ["/services/technical", "Техническая обработка"],
    ["/about", "Об исполнителе"],
    ["/publications", "Публикации"],
    ["/contacts", "Контакты"],
  ]) {
    const response = await request.get(path);
    expect(response.status()).toBe(200);
    expect(await response.text()).toContain(title);
  }
  expect((await request.get("/publications/missing")).status()).toBe(404);
});

test("consultation sends both contacts, shows success and handles throttling", async ({
  page,
}) => {
  await page.route("**/api/auth/csrf", (r) =>
    r.fulfill({ json: { csrf_token: "test" } }),
  );
  let attempts = 0;
  await page.route("**/api/consultations", async (r) => {
    expect(r.request().postDataJSON()).toEqual({
      email: "reader@example.com",
      phone: "+79991234567",
    });
    expect(r.request().headers()["x-csrf-token"]).toBe("test");
    attempts++;
    await r.fulfill({ status: attempts === 1 ? 429 : 202, json: {} });
  });
  await page.goto("/contacts");
  await page.getByLabel("Ваш email").fill("reader@example.com");
  await page.getByLabel("Ваш телефон").fill("+7 (999) 123-45-67");
  await page.getByRole("button", { name: "Запросить консультацию" }).click();
  await expect(page.getByRole("alert")).toContainText("Слишком много запросов");
  await page.getByRole("button", { name: "Запросить консультацию" }).click();
  await expect(page.getByRole("status")).toContainText("Заявка принята");
});

test("presentation video plays and public pages fit wide and mobile screens", async ({
  page,
}) => {
  await page.goto("/");
  const video = page.locator("video");
  await expect(video).toHaveAttribute("controls", "");
  await expect(video).toHaveAttribute(
    "poster",
    new RegExp(`${encodeURI("заставка")}.*\\.jpg$`),
  );
  await expect(video.locator("source")).toHaveAttribute(
    "src",
    new RegExp(`${encodeURI("Презентация_1")}\\.1.*\\.mp4$`),
  );
  await video.evaluate(async (element: HTMLVideoElement) => {
    await element.play();
  });
  await expect
    .poll(() =>
      video.evaluate((element: HTMLVideoElement) => element.currentTime),
    )
    .toBeGreaterThan(0);
  await video.evaluate((element: HTMLVideoElement) => element.pause());
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    for (const path of [
      "/",
      "/services/ai-analysis",
      "/services/technical",
      "/about",
      "/publications",
      "/contacts",
    ]) {
      await page.goto(path);
      await expect(page.locator("h1")).toBeVisible();
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth),
      ).toBeLessThanOrEqual(width);
      await page.screenshot({
        path: `/tmp/sinegor-f4/${width}-${path.replaceAll("/", "_") || "home"}.png`,
        fullPage: true,
      });
    }
  }
  await page.getByRole("button", { name: "Открыть меню", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("link", { name: "Публикации", exact: true })
    .click();
  await expect(page).toHaveURL(/\/publications$/);
  await expect(page.getByRole("dialog")).not.toBeVisible();
});
