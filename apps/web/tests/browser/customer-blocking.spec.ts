import { test, expect } from "@playwright/test";
import { mockApi, customerId } from "./mock-api";

for (const width of [1440, 390]) {
  test(`customer block and unblock with keyboard ${width}`, async ({
    page,
  }, info) => {
    await page.setViewportSize({ width, height: 900 });
    const state = await mockApi(page);
    const customer = state.customers[0];
    Object.assign(customer, {
      blocked_at: null,
      block_reason: null,
      block_comment: null,
    });
    const calls: unknown[] = [];
    await page.route(
      `**/api/admin/customers/${customerId}/*block`,
      async (route) => {
        const req = route.request();
        calls.push(req.method());
        expect(req.headers()["x-csrf-token"]).toBe("test-csrf");
        if (req.url().endsWith("/unblock")) {
          Object.assign(customer, {
            blocked_at: null,
            block_reason: null,
            block_comment: null,
          });
        } else {
          const body = req.postDataJSON();
          calls.push(body);
          Object.assign(customer, {
            blocked_at: "2026-11-06T01:00:00Z",
            block_reason: body.reason,
            block_comment: body.internal_comment,
          });
        }
        return route.fulfill({ json: customer });
      },
    );
    await page.goto(`/admin/customers/${customerId}`);
    await expect(
      page.getByText("Доступ разрешён", { exact: true }),
    ).toBeVisible();
    await expect(page.getByText(/Блокировка действует только/)).toBeVisible();
    await page
      .getByLabel("Причина для заказчика")
      .fill('<img src=x onerror="window.injected=1">');
    await page.getByLabel("Внутренний комментарий").fill("Внутренние сведения");
    await page
      .getByRole("button", { name: "Заблокировать", exact: true })
      .focus();
    await page.keyboard.press("Enter");
    await expect(
      page.getByText("Доступ заблокирован", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText('<img src=x onerror="window.injected=1">', {
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      page.getByText("Внутренние сведения", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Повторить приглашение" }),
    ).toBeDisabled();
    expect(
      await page.evaluate(
        () => (window as unknown as { injected?: number }).injected,
      ),
    ).toBeUndefined();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: info.outputPath(`blocked-${width}.png`),
      fullPage: true,
    });
    await page
      .getByRole("button", { name: "Разблокировать", exact: true })
      .focus();
    await page.keyboard.press("Enter");
    await expect(
      page.getByText("Доступ разрешён", { exact: true }),
    ).toBeVisible();
    await expect(page.getByLabel("Причина для заказчика")).toHaveValue("");
    await expect(
      page.getByText("Внутренние сведения", { exact: true }),
    ).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Повторить приглашение" }),
    ).toBeEnabled();
    expect(calls.length).toBe(3);
  });
}

test("blocking validation and server error keep the form", async ({ page }) => {
  await mockApi(page);
  await page.route(`**/api/admin/customers/${customerId}/block`, (route) =>
    route.fulfill({ status: 503, json: { error: { message: "Unavailable" } } }),
  );
  await page.goto(`/admin/customers/${customerId}`);
  await page
    .getByRole("button", { name: "Заблокировать", exact: true })
    .click();
  await expect(page.getByLabel("Причина для заказчика")).toBeFocused();
  await page.getByLabel("Причина для заказчика").fill("Синтетическая причина");
  await page
    .getByRole("button", { name: "Заблокировать", exact: true })
    .click();
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page.getByLabel("Причина для заказчика")).toHaveValue(
    "Синтетическая причина",
  );
});
