import { test, expect } from "@playwright/test";
import { mockApi, folder, deletion, orderId, deletionId } from "./mock-api";

for (const width of [390, 1440]) {
  test(`deferred request supports one deletion and reminder editing at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 });
    const state = await mockApi(page);
    state.order.status = "cancelled";
    state.deletion = {
      ...deletion(),
      status: "deferred",
      reason: "order_cancelled",
      deferred_until: "2030-01-06T11:30:00Z",
      admin_note: "Поступило обращение",
    };
    state.folder = folder();
    await page.goto(`/admin/orders/${orderId}`);
    const card = page.locator(".retention-card");
    await expect(
      card.getByRole("button", {
        name: "Подтвердить решение об удалении",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      card.getByRole("button", { name: "Удалить материалы", exact: true }),
    ).toBeEnabled();
    const date = card.getByLabel("Следующее напоминание (МСК)");
    await expect(date).toHaveValue("2030-01-06T14:30");
    await expect(card.getByLabel("Причина отсрочки")).toHaveValue(
      "Поступило обращение",
    );
    await date.fill("2030-01-04T13:00");
    await card
      .getByRole("button", { name: "Изменить дату напоминания", exact: true })
      .click();
    await expect(
      page.getByText("Дата следующего напоминания сохранена.", { exact: true }),
    ).toBeVisible();
    expect(state.calls.find((c) => c.path.endsWith("/defer"))?.body).toEqual({
      deletion_request_id: deletionId,
      deferred_until: "2030-01-04T10:00:00.000Z",
      note: "Поступило обращение",
    });
    expect(state.deleteCount).toBe(0);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(width);
    await card.screenshot({
      path: `/tmp/sinegor-t12-23-5/retention-${width}.png`,
      animations: "disabled",
    });
    await card
      .getByRole("button", { name: "Удалить материалы", exact: true })
      .click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText(state.folder.disk_path);
    await expect(dialog).toContainText("без корзины");
    await page.screenshot({
      path: `/tmp/sinegor-t12-23-5/delete-dialog-${width}.png`,
      animations: "disabled",
    });
    await dialog
      .getByLabel("Подтверждаю запуск или проверку", { exact: false })
      .check();
    await dialog
      .getByRole("button", {
        name: "Подтвердить операцию удаления",
        exact: true,
      })
      .click();
    await expect(dialog).not.toBeVisible();
    expect(state.calls.filter((c) => c.path.endsWith("/confirm"))).toHaveLength(
      0,
    );
    expect(state.deleteCount).toBe(1);
  });
}

test("failed deletion stays open and busy prevents duplicate requests", async ({
  page,
}) => {
  const state = await mockApi(page);
  state.deletion = deletion();
  state.folder = folder();
  let release!: () => void;
  const gate = new Promise<void>((resolve) => (release = resolve));
  let attempts = 0;
  await page.route("**/api/admin/orders/*/folder/delete", async (route) => {
    attempts++;
    await gate;
    await route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({
        error: { code: "disk_unavailable", message: "Disk unavailable" },
      }),
    });
  });
  await page.goto(`/admin/orders/${orderId}`);
  await page
    .getByRole("button", { name: "Удалить материалы", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await dialog
    .getByLabel("Подтверждаю запуск или проверку", { exact: false })
    .check();
  const submit = dialog.getByRole("button", {
    name: "Подтвердить операцию удаления",
    exact: true,
  });
  await submit.click();
  await expect(submit).toBeDisabled();
  await expect(
    dialog.getByRole("button", { name: "Закрыть", exact: true }),
  ).toBeDisabled();
  expect(attempts).toBe(1);
  release();
  await expect(
    dialog.getByText("Удаление не подтверждено.", { exact: false }),
  ).toBeVisible();
  await expect(submit).toBeEnabled();
  await expect(page.locator(".retention-card .badge")).toHaveText(
    "Ожидает решения",
  );
  expect(state.deleteCount).toBe(0);
});
