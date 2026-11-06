import { test, expect } from "@playwright/test";

test("SSR footer links to the same about page as the main navigation", async ({
  request,
}) => {
  for (const path of ["/", "/about", "/documents", "/auth/login"]) {
    const response = await request.get(path);
    expect(response.status()).toBe(path === "/documents" ? 503 : 200);
    const html = await response.text();
    const footer = html.match(/<footer\b[^>]*>[\s\S]*?<\/footer>/)?.[0];
    expect(footer).toMatch(/<a\b[^>]*href="\/about"[^>]*>Об исполнителе<\/a>/);
    expect(footer?.match(/href="\/about"/g)).toHaveLength(1);
    expect(footer).not.toContain("/documents/provider-information");
    for (const slug of [
      "privacy-policy",
      "personal-data-consent",
      "service-rules",
    ])
      expect(footer).toContain(`href="/documents/${slug}"`);
    if (!path.startsWith("/auth/"))
      expect(html.split("</header>")[0]).toMatch(
        /<a\b[^>]*href="\/about"[^>]*>Обо мне<\/a>/,
      );
  }
});

for (const width of [1440, 390]) {
  test(`footer and main menu open the same about page with keyboard at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/documents");
    const footer = page.getByRole("contentinfo");
    const about = footer.getByRole("link", {
      name: "Об исполнителе",
      exact: true,
    });
    await expect(about).toHaveCount(1);
    await expect(about).toHaveAttribute("href", "/about");
    await expect(footer.getByRole("link")).toHaveCount(4);
    await expect(
      footer.locator('a[href="/documents/provider-information"]'),
    ).toHaveCount(0);
    await footer
      .getByRole("link", { name: "Правила предоставления услуг", exact: true })
      .focus();
    await page.keyboard.press("Tab");
    await expect(about).toBeFocused();
    expect(
      await about.evaluate((element) => getComputedStyle(element).outlineStyle),
    ).not.toBe("none");
    await expect(about).toBeInViewport();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(width);
    await page.screenshot({
      path: `/tmp/sinegor-t12-05/footer-${width}.png`,
      fullPage: true,
      animations: "disabled",
    });
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/about$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      "Об исполнителе",
    );
    await page.goto("/documents");
    const menu =
      width < 768
        ? page.getByRole("dialog")
        : page.getByRole("navigation", { name: "Основная навигация" });
    if (width < 768) {
      await page
        .getByRole("button", { name: "Открыть меню", exact: true })
        .focus();
      await page.keyboard.press("Enter");
    }
    await menu.getByRole("link", { name: "Обо мне", exact: true }).focus();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/about$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      "Об исполнителе",
    );
  });
}
