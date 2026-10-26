import { test, expect } from "@playwright/test";

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

test("generated video plays and public pages fit wide and mobile screens", async ({
  page,
}) => {
  await page.goto("/");
  const video = page.locator("video");
  await expect(video).toHaveAttribute("controls", "");
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
