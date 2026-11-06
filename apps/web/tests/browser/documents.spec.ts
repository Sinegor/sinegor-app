import { test, expect } from "@playwright/test";

test("unconfigured CMS returns 503 without frontend document placeholders", async ({
  request,
}) => {
  for (const path of [
    "/documents",
    "/documents/privacy-policy",
    "/documents/personal-data-consent",
    "/documents/service-rules",
    "/documents/provider-information",
    "/documents/unknown",
  ]) {
    const response = await request.get(path);
    expect(response.status()).toBe(503);
    expect(response.headers()["cache-control"]).toBe("no-store");
    const html = await response.text();
    expect(html).toContain("Документы временно недоступны");
    expect(html).not.toContain("Документ готовится к публикации");
    expect(html.split("</head>")[0]).toContain(
      'name="robots" content="noindex, follow"',
    );
    expect(html.split("</head>")[0]).not.toContain('rel="canonical"');
  }
});

test("public footer and documents fit desktop and mobile and support keyboard navigation", async ({
  page,
}) => {
  await page.route("**/api/auth/session", (route) =>
    route.fulfill({ status: 401, json: {} }),
  );
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    for (const path of [
      "/documents",
      "/documents/privacy-policy",
      "/publications",
      "/auth/login",
    ]) {
      await page.goto(path);
      const footer = page.getByRole("contentinfo");
      await expect(footer).toContainText(
        "IT-лаборатория адвоката Артемьева Д. В.",
      );
      await expect(footer).toContainText(
        `© ${new Intl.DateTimeFormat("en", { year: "numeric", timeZone: "Europe/Moscow" }).format(new Date())} SINEGOR LAB`,
      );
      await expect(footer.getByRole("link")).toHaveCount(4);
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth),
      ).toBeLessThanOrEqual(width);
      const mainBox = await page.locator("main").boundingBox();
      const footerBox = await footer.boundingBox();
      expect(footerBox!.y).toBeGreaterThanOrEqual(
        mainBox!.y + mainBox!.height - 1,
      );
      await page.screenshot({
        path: `/tmp/t1104-reference/${width}-${path.replaceAll("/", "_")}.png`,
        fullPage: true,
      });
    }
  }
  await page.goto("/documents");
  await page.getByRole("button", { name: "Открыть меню", exact: true }).click();
  const menu = page.getByRole("dialog");
  await expect(
    menu.getByRole("link", { name: "Контакты", exact: true }),
  ).toHaveCount(0);
  await menu.getByRole("link", { name: "Документы", exact: true }).click();
  await expect(menu).not.toBeVisible();
  const first = page.getByRole("contentinfo").getByRole("link").first();
  await first.focus();
  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("contentinfo").getByRole("link").nth(1),
  ).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/documents\/personal-data-consent$/);
});
