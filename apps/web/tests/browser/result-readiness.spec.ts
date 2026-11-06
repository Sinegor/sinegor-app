import { test, expect } from "@playwright/test";
import { mockApi, agreement, folder, orderId } from "./mock-api";

for (const width of [1440, 390]) {
  test(`readiness uses only result upload confirmation with keyboard at ${width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    const state = await mockApi(page);
    state.order.status = "in_progress";
    state.agreement = agreement("approved", 3);
    state.folder = folder();
    await page.goto(`/admin/orders/${orderId}`);
    const card = page.locator("section.card").filter({
      has: page.getByRole("heading", {
        name: "Изменение статуса",
        exact: true,
      }),
    });
    const form = card.locator("form");
    const uploaded = form.getByRole("checkbox", {
      name: "Результат размещён в папке заказа",
      exact: true,
    });
    const submit = form.getByRole("button", {
      name: "Зафиксировать готовность",
      exact: true,
    });
    await expect(form.getByRole("checkbox")).toHaveCount(1);
    await expect(page.locator('[name="access_read_only"]')).toHaveCount(0);
    await expect(card).not.toContainText(/изменил права|режим просмотра/);
    await expect(uploaded).not.toBeChecked();
    await submit.click();
    await expect(uploaded).toBeFocused();
    expect(
      state.calls.filter(
        (c) => c.method === "POST" && c.path.endsWith("/status"),
      ),
    ).toHaveLength(0);
    await page.keyboard.press("Tab");
    await expect(submit).toBeFocused();
    await page.keyboard.press("Shift+Tab");
    await expect(uploaded).toBeFocused();
    await page.keyboard.press("Space");
    await expect(uploaded).toBeChecked();
    await page.keyboard.press("Tab");
    await expect(submit).toBeFocused();
    expect(
      await submit.evaluate((el) => getComputedStyle(el).outlineStyle),
    ).not.toBe("none");
    await expect(uploaded).toBeInViewport({ ratio: 1 });
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(width);
    await card.screenshot({
      path: testInfo.outputPath(`ready-${width}.png`),
      animations: "disabled",
    });
    await page.keyboard.press("Enter");
    await expect(
      page.getByText("Результат готов, письмо принято почтовым сервисом.", {
        exact: true,
      }),
    ).toBeVisible();
    const changes = state.calls.filter(
      (c) => c.method === "POST" && c.path.endsWith("/status"),
    );
    expect(changes).toHaveLength(1);
    expect(changes[0].body).toEqual({
      status: "result_ready",
      result_uploaded: true,
    });
    expect(changes[0].csrf).toBe("test-csrf");
    // No new operation on the folder is triggered by readiness.
    expect(
      state.calls.filter(
        (c) => c.method !== "GET" && c.path.includes("/folder"),
      ),
    ).toHaveLength(0);
    await expect(submit).toHaveCount(0);
    await page.reload();
    await expect(card).toContainText(
      "Заказ завершится автоматически через 14 календарных дней",
    );
    await expect(form).toHaveCount(0);
  });
}
