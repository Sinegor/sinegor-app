import { test, expect } from "@playwright/test";
import {
  customerApi,
  customerAgreement,
  customerOrderId,
} from "./customer-api";

// Exact approved copy from Т1.2-09, independent of the rendered component.
const warningText =
  "Важно: подтверждайте передачу материалов только после того, как все документы будут полностью загружены на Яндекс Диск. До завершения загрузки не устанавливайте соответствующую отметку и не отправляйте уведомление исполнителю.";

for (const width of [1440, 390]) {
  test(`handover warning precedes explicit keyboard confirmation at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    const state = await customerApi(page);
    state.order.status = "awaiting_materials";
    state.agreement = customerAgreement("approved", 3);
    state.folder = { folder_url: "https://disk.yandex.ru/invite/synthetic" };
    await page.goto(`/customer/orders/${customerOrderId}`);
    const card = page.locator("section.card").filter({
      has: page.getByRole("heading", { name: "Материалы заказа", exact: true }),
    });
    const submit = card.getByRole("button", {
      name: "Подтвердить передачу материалов",
      exact: true,
    });
    const form = card.locator("form");
    await expect(form).toHaveCount(1);
    const warning = form.locator('.notice[data-tone="warning"]');
    await expect(warning).toHaveText(warningText);
    await expect(warning.locator("strong")).toHaveText("Важно:");
    const confirmation = form.getByRole("checkbox", {
      name: "Я завершил передачу материалов в папку заказа на Яндекс Диске",
      exact: true,
    });
    expect(
      await confirmation.evaluate((checkbox) =>
        checkbox
          .closest("label")
          ?.previousElementSibling?.textContent?.trim()
          .replace(/\s+/g, " "),
      ),
    ).toBe(warningText);
    await expect(confirmation).not.toBeChecked();
    await submit.click();
    await expect(confirmation).toBeFocused();
    expect(state.calls.filter((call) => call.method === "POST")).toHaveLength(
      0,
    );
    await form
      .getByLabel("Примечание к передаче (необязательно)")
      .fill("Синтетический комплект передан");
    await page.keyboard.press("Tab");
    await expect(confirmation).toBeFocused();
    await expect(warning).toBeInViewport({ ratio: 1 });
    expect(
      await confirmation.evaluate(
        (element) => getComputedStyle(element).outlineStyle,
      ),
    ).not.toBe("none");
    await page.keyboard.press("Space");
    await expect(confirmation).toBeChecked();
    await page.keyboard.press("Tab");
    await expect(submit).toBeFocused();
    await expect(warning).toBeInViewport({ ratio: 1 });
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(width);
    expect(state.calls.filter((call) => call.method === "POST")).toHaveLength(
      0,
    );
    await card.screenshot({
      path: `/tmp/sinegor-t12-09/handover-${width}.png`,
      animations: "disabled",
    });
    await page.keyboard.press("Enter");
    await expect(
      page
        .getByRole("status")
        .filter({ hasText: "Передача материалов отмечена" })
        .first(),
    ).toBeVisible();
    const submitted = state.calls.filter(
      (call) => call.method === "POST" && call.path.endsWith("/materials"),
    );
    expect(submitted).toHaveLength(1);
    expect(submitted[0].body).toEqual({
      note: "Синтетический комплект передан",
    });
    expect(submitted[0].csrf).toBe("customer-csrf");
    await expect(submit).toHaveCount(0);
    await expect(warning).toHaveCount(0);
    await page.reload();
    await expect(card).toContainText("Синтетический комплект передан");
    await expect(form).toHaveCount(0);
  });
}
