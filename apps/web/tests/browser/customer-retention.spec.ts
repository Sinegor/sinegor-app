import { test, expect } from "@playwright/test";
import {
  customerApi,
  customerAgreement,
  customerDeletion,
  customerOrderId,
  now,
} from "./customer-api";

// Approved copy from Т1.2-7, independent of the component under test.
const paragraphs = [
  "Исходные документы и результаты исследования хранятся на Яндекс Диске в течение 14 календарных дней после уведомления о готовности результата.",
  "В этот период возможно проведение дополнительных исследований без повторной загрузки документов. Бесплатно — если потребуется устранить выявленную неполноту выполненной работы. Платно — если у вас появятся новые задачи.",
  "По истечении 14 дней заказ автоматически завершается, и исполнителю поступает запрос на удаление материалов. Для проведения исследований после окончания срока хранения документы потребуется загрузить повторно.",
  "Если дальнейшая работа с материалами не планируется, вы можете разрешить их досрочное удаление. Подписанное соглашение сохраняется.",
];

for (const width of [1440, 390]) {
  test(`approved retention copy stays beside the permission action at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    const state = await customerApi(page);
    state.order.status = "result_ready";
    state.order.ready_at = now;
    state.order.result_notified_at = now;
    state.agreement = customerAgreement("approved", 3);
    await page.goto(`/customer/orders/${customerOrderId}`);
    const card = page.locator(".retention-card");
    await expect(card.getByRole("heading", { level: 2 })).toHaveText(
      "Хранение и удаление материалов",
    );
    const text = card.locator(":scope > p");
    await expect(text).toHaveCount(4);
    for (const [i, paragraph] of paragraphs.entries())
      await expect(text.nth(i)).toHaveText(paragraph);
    const authorize = card.getByRole("button", {
      name: "Разрешить удаление материалов",
      exact: true,
    });
    await expect(authorize).toBeEnabled();
    expect(
      await authorize.evaluate((button) =>
        button.previousElementSibling?.textContent?.trim().replace(/\s+/g, " "),
      ),
    ).toBe(paragraphs[3]);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(width);
    await authorize.focus();
    await expect(authorize).toBeFocused();
    expect(
      await authorize.evaluate(
        (element) => getComputedStyle(element).outlineStyle,
      ),
    ).not.toBe("none");
    await page.screenshot({
      path: `/tmp/sinegor-t12-07/retention-${width}.png`,
      fullPage: true,
      animations: "disabled",
    });
    await page.keyboard.press("Enter");
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText(
      "Само удаление выполняется только после отдельного подтверждения исполнителя.",
    );
    await page.keyboard.press("Escape");
    await expect(dialog).not.toBeVisible();
    await expect(authorize).toBeFocused();
    expect(state.calls.filter((call) => call.method === "POST")).toHaveLength(
      0,
    );

    for (const status of ["waiting", "deferred", "performed"] as const) {
      state.deletion = customerDeletion();
      state.deletion.status = status;
      if (status === "deferred") state.deletion.deferred_until = now;
      if (status === "performed") {
        state.order.status = "completed";
        state.deletion.performed_at = now;
      }
      await page.reload();
      for (const [i, paragraph] of paragraphs.entries())
        await expect(text.nth(i)).toHaveText(paragraph);
      await expect(card.locator(".badge")).toHaveText(
        {
          waiting: "Ожидается решение исполнителя",
          deferred: "Удаление отложено",
          performed: "Материалы удалены",
        }[status],
      );
      if (status === "performed") await expect(authorize).toHaveCount(0);
      else await expect(authorize).toBeEnabled();
    }
  });
}
