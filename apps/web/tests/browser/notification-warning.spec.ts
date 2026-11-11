import { test, expect } from "@playwright/test";
import { mockApi } from "./mock-api";

for (const width of [1440, 390]) {
  test(`delivery warnings keep channels and reasons separate at ${width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await mockApi(page);
    await page.route("**/api/admin/notifications/summary", (route) =>
      route.fulfill({
        json: [
          { channel: "smtp", reason: "delayed", count: 2 },
          { channel: "telegram", reason: "permanent", count: 1 },
          { channel: "smtp", reason: "expired", count: 1 },
        ],
      }),
    );
    await page.goto("/admin/customers");
    const notice = page
      .getByRole("status")
      .filter({ hasText: "Проблемные уведомления" });
    await expect(notice).toBeVisible();
    await expect(notice).toContainText("Количество проблемных уведомлений: 4.");
    await expect(notice.getByRole("link")).toHaveAttribute(
      "href",
      "/admin/consultations?view=notifications#notification-problems",
    );
    await expect(notice).toContainText(
      "Email: отправка задерживается более 24 часов — 2",
    );
    await expect(notice).toContainText("Telegram: ошибка отправки — 1");
    await expect(notice).toContainText(
      "Email: срок автоматических повторов истёк — 1",
    );
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: testInfo.outputPath(`delivery-${width}.png`),
      fullPage: true,
    });
    await page.keyboard.press("Tab");
    await expect(
      page.getByRole("link", { name: "Перейти к содержимому" }),
    ).toBeFocused();
    await page.keyboard.press("Enter");
    await page.getByRole("heading", { name: "Контакты и заказы" }).waitFor();
  });
}

test("warning fetch failure is visible and does not block administrative work", async ({
  page,
}) => {
  await mockApi(page);
  await page.route("**/api/admin/notifications/summary", (route) =>
    route.fulfill({ status: 503, json: {} }),
  );
  await page.goto("/admin/customers");
  await expect(
    page.getByText("Не удалось проверить отправку уведомлений."),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Контакты и заказы" }),
  ).toBeVisible();
});

test("a hanging delivery summary cannot block administrative work", async ({
  page,
}) => {
  await mockApi(page);
  await page.route("**/api/admin/notifications/summary", async () => {
    await new Promise(() => {});
  });
  await page.goto("/admin/customers");
  await expect(
    page.getByRole("heading", { name: "Контакты и заказы" }),
  ).toBeVisible();
});

test("delivery warning refreshes while the admin page remains open", async ({
  page,
}) => {
  await page.clock.install();
  await mockApi(page);
  let rows: { channel: string; reason: string; count: number }[] = [];
  let requests = 0;
  await page.route("**/api/admin/notifications/summary", (route) => {
    requests++;
    return route.fulfill({ json: rows });
  });
  await page.goto("/admin/customers");
  await expect.poll(() => requests).toBe(1);
  await expect(
    page.getByRole("heading", { name: "Контакты и заказы" }),
  ).toBeVisible();
  rows = [{ channel: "smtp", reason: "delayed", count: 1 }];
  await page.clock.fastForward(60000);
  await expect(
    page.getByRole("status").filter({ hasText: "Проблемные уведомления" }),
  ).toContainText("Email: отправка задерживается более 24 часов — 1");
  rows = [];
  await page.clock.fastForward(60000);
  await expect(
    page.getByText("Проблемные уведомления", { exact: true }),
  ).toHaveCount(0);
});
