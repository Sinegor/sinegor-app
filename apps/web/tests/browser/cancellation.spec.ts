import { test, expect } from "@playwright/test";
import { mockApi, folder, orderId } from "./mock-api";
import {
  customerApi,
  customerOrderId,
  customerAgreement,
  customerDeletion,
} from "./customer-api";

for (const width of [390, 1440]) {
  test(`cancellation requires both reasons and recovers from API error at ${width}`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 960 });
    const state = await mockApi(page);
    state.order.status = "in_progress";
    state.folder = folder();
    await page.goto(`/admin/orders/${orderId}`);
    await page
      .getByRole("button", { name: "Отменить заказ", exact: true })
      .click();
    const dialog = page.getByRole("dialog");
    const confirm = dialog.getByRole("button", {
      name: "Подтвердить отмену заказа",
      exact: true,
    });
    await confirm.click();
    expect(state.calls.filter((c) => c.path.endsWith("/status"))).toHaveLength(
      0,
    );
    const internal = dialog.getByLabel("Основание отмены заказа", {
      exact: true,
    });
    const customer = dialog.getByLabel("Причина отмены для заказчика", {
      exact: true,
    });
    await internal.fill(" ");
    await customer.fill("Customer <script>unsafe()</script>\nExplanation");
    await confirm.click();
    expect(state.calls.filter((c) => c.path.endsWith("/status"))).toHaveLength(
      0,
    );
    await internal.fill("Private internal decision");
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: `../../docs/reports/t12-23-4-cancellation-2026-11-06/dialog-${width}.png`,
    });
    await page.route(
      "**/api/admin/orders/*/status",
      (route) => route.fulfill({ status: 503, json: {} }),
      { times: 1 },
    );
    await confirm.click();
    await expect(dialog.getByRole("alert")).toBeVisible();
    await expect(internal).toHaveValue("Private internal decision");
    await expect(customer).toHaveValue(
      "Customer <script>unsafe()</script>\nExplanation",
    );
    await expect(dialog).toBeVisible();
    let release!: () => void;
    state.mutationGate = new Promise<void>((resolve) => {
      release = resolve;
    });
    await confirm.click();
    await expect(confirm).toBeDisabled();
    await expect(
      dialog.getByRole("button", { name: "Закрыть", exact: true }),
    ).toBeDisabled();
    release();
    state.mutationGate = null;
    await expect(dialog).not.toBeVisible();
    const reasons = page.getByRole("region", { name: "Причины отмены" });
    await expect(reasons).toContainText("Private internal decision");
    await expect(reasons).toContainText("Customer <script>unsafe()</script>");
    await expect(reasons.locator("script")).toHaveCount(0);
    const calls = state.calls.filter((c) => c.path.endsWith("/status"));
    expect(calls).toHaveLength(1);
    expect(calls[0].body).toMatchObject({
      status: "cancelled",
      cancellation_internal_reason: "Private internal decision",
      cancellation_customer_reason:
        "Customer <script>unsafe()</script>\nExplanation",
    });
    expect(calls[0].csrf).toBe("test-csrf");
    expect(state.deleteCount).toBe(0);
    await expect(
      page.getByText("Отмена заказа", { exact: true }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: `../../docs/reports/t12-23-4-cancellation-2026-11-06/admin-${width}.png`,
      fullPage: true,
    });
  });

  for (const historical of [false, true]) {
    test(`cancelled customer explanation ${historical ? "historical" : "new"} keeps folder at ${width}`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 960 });
      const state = await customerApi(page);
      state.order.status = "cancelled";
      state.order.closed_at = "2026-11-06T10:00:00Z";
      state.order.cancellation_customer_reason = historical
        ? null
        : "Customer <script>unsafe()</script>\nExplanation";
      state.agreement = customerAgreement("approved", 3);
      state.folder = { folder_url: "https://disk.yandex.ru/invite/synthetic" };
      state.deletion = customerDeletion();
      state.deletion.reason = "order_cancelled";
      await page.goto(`/customer/orders/${customerOrderId}`);
      const reason = page.getByRole("region", {
        name: "Причина отмены заказа",
      });
      await expect(reason).toContainText(
        historical
          ? "Причина отмены не указана"
          : "Customer <script>unsafe()</script>",
      );
      await expect(reason.locator("script")).toHaveCount(0);
      await expect(
        page.getByRole("link", {
          name: "Открыть папку на Яндекс Диске",
          exact: false,
        }),
      ).toHaveAttribute("href", "https://disk.yandex.ru/invite/synthetic");
      await expect(
        page.getByText("Передайте документы непосредственно", { exact: false }),
      ).toHaveCount(0);
      const retention = page.locator(".retention-card");
      await expect(retention).not.toContainText("14 календарных дней");
      await expect(
        page.getByRole("button", {
          name: "Разрешить удаление материалов",
          exact: true,
        }),
      ).toHaveCount(0);
      expect(state.calls.every((c) => c.method === "GET")).toBe(true);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= window.innerWidth,
        ),
      ).toBe(true);
      if (!historical)
        await page.screenshot({
          path: `../../docs/reports/t12-23-4-cancellation-2026-11-06/customer-${width}.png`,
          fullPage: true,
        });
      state.folder = null;
      state.deletion.status = "performed";
      state.deletion.performed_at = "2026-11-06T11:00:00Z";
      await page
        .getByRole("button", { name: "Обновить заказ", exact: true })
        .click();
      await expect(
        page.getByRole("link", {
          name: "Открыть папку на Яндекс Диске",
          exact: false,
        }),
      ).toHaveCount(0);
      await expect(
        page.getByText(
          "Материалы удалены, ссылка на папку больше недоступна.",
          { exact: true },
        ),
      ).toBeVisible();
    });
  }
}

for (const width of [390, 1440]) {
  test(`historical cancellation explains missing administrative basis at ${width}`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 960 });
    const state = await mockApi(page);
    state.order.status = "cancelled";
    state.order.closed_at = "2026-11-06T10:00:00Z";
    await page.goto(`/admin/orders/${orderId}`);
    const reasons = page.getByRole("region", { name: "Причины отмены" });
    await expect(reasons).toContainText(
      "Основание отмены исторически не зафиксировано",
    );
    await expect(reasons).toContainText("Причина отмены не указана");
    await expect(
      page.getByRole("button", { name: "Отменить заказ", exact: true }),
    ).toHaveCount(0);
  });
}
