import { test, expect } from "@playwright/test";
import { mockApi } from "./mock-api";

const event = {
  id: "f9588fa1-8fea-4872-b1ba-30a4262f155e",
  kind: "materials_deleted",
  channel: "smtp",
  reason: "delayed",
  status: "pending",
  created_at: "2026-11-06T16:54:34Z",
  available_at: "2026-11-06T16:54:34Z",
  attempts: 0,
  error_code: null,
  order_id: "5d1de808-2b39-4ad0-90c5-ac852b690988",
  customer_id: null,
};

for (const width of [1440, 390]) {
  test(`warning opens its non-consultation event and refresh clears it at ${width}px`, async ({
    page,
  }, info) => {
    await page.setViewportSize({ width, height: 900 });
    await mockApi(page);
    let active = true;
    await page.route("**/api/admin/notifications/summary", (route) =>
      route.fulfill({
        json: active ? [{ channel: "smtp", reason: "delayed", count: 1 }] : [],
      }),
    );
    await page.route("**/api/admin/notifications/problems?*", (route) =>
      route.fulfill({ json: active ? [event] : [] }),
    );
    await page.goto("/admin/customers");
    await page.getByRole("link", { name: "Открыть проблемы доставки" }).click();
    await expect(page).toHaveURL(/view=notifications/);
    await expect(
      page.getByRole("heading", { name: "Уведомление об удалении материалов" }),
    ).toBeVisible();
    await expect(page.getByText(event.id, { exact: true })).toBeVisible();
    await expect(
      page.getByText("Попыток отправки не было.", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: "Открыть заказ" }),
    ).toHaveAttribute("href", `/admin/orders/${event.order_id}`);
    await expect(
      page.getByText("Недоставленных консультационных заявок нет."),
    ).toHaveCount(0);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: info.outputPath(`problems-${width}.png`),
      fullPage: true,
    });
    active = false;
    await page.getByRole("button", { name: "Обновить", exact: true }).click();
    await expect(
      page.getByText("Актуальных проблем доставки нет.", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("status").filter({ hasText: "Проблемы доставки" }),
    ).toHaveCount(0);
  });
}

test("handling a consultation refreshes the warning immediately", async ({
  page,
}) => {
  await mockApi(page);
  let active = true;
  const id = "c55eaa2e-bad0-43d1-9b04-22aa7c439eee";
  await page.route("**/api/admin/notifications/summary", (route) =>
    route.fulfill({
      json: active ? [{ channel: "smtp", reason: "permanent", count: 1 }] : [],
    }),
  );
  await page.route("**/api/admin/consultations**", (route) => {
    if (route.request().method() === "POST") {
      active = false;
      return route.fulfill({ json: { message: "ok" } });
    }
    return route.fulfill({
      json: active
        ? [
            {
              id,
              created_at: new Date().toISOString(),
              contacts_expires_at: new Date(
                Date.now() + 86400000,
              ).toISOString(),
              observed_at: new Date().toISOString(),
              email: "test@example.test",
              phone: "+79991234567",
              contacts_expiring: false,
              status: "unresolved",
              can_handle: true,
              can_retry: true,
              channels: [
                {
                  channel: "smtp",
                  status: "failed",
                  reason: "permanent",
                  attention: true,
                  retry_after: null,
                },
              ],
            },
          ]
        : [],
    });
  });
  await page.goto("/admin/consultations");
  await expect(
    page.getByRole("status").filter({ hasText: "Проблемы доставки" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Отметить обработанным", exact: true })
    .click();
  await page.getByRole("button", { name: "Подтвердить обработку" }).click();
  await expect(
    page.getByText("Недоставленных консультационных заявок нет."),
  ).toBeVisible();
  await expect(
    page.getByRole("status").filter({ hasText: "Проблемы доставки" }),
  ).toHaveCount(0);
});

test("problem list failure is visible instead of an empty state", async ({
  page,
}) => {
  await mockApi(page);
  await page.route("**/api/admin/notifications/problems?*", (route) =>
    route.fulfill({ status: 503, json: {} }),
  );
  await page.goto("/admin/consultations?view=notifications");
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Повторить загрузку" }),
  ).toBeVisible();
  await expect(page.getByText("Актуальных проблем доставки нет.")).toHaveCount(
    0,
  );
});

test("an empty later page keeps the warning and offers the first page", async ({
  page,
}) => {
  await mockApi(page);
  await page.route("**/api/admin/notifications/summary", (route) =>
    route.fulfill({ json: [{ channel: "smtp", reason: "delayed", count: 1 }] }),
  );
  await page.route("**/api/admin/notifications/problems?*", (route) => {
    const offset = new URL(route.request().url()).searchParams.get("offset");
    return route.fulfill({ json: offset === "0" ? [event] : [] });
  });
  await page.goto("/admin/consultations?view=notifications&offset=25");
  await expect(
    page.getByRole("status").filter({ hasText: "Проблемы доставки" }),
  ).toBeVisible();
  await expect(
    page.getByText("Актуальных проблем доставки нет.", { exact: true }),
  ).toHaveCount(0);
  await page
    .getByRole("link", { name: "В начало списка", exact: true })
    .click();
  await expect(page.getByText(event.id, { exact: true })).toBeVisible();
});
