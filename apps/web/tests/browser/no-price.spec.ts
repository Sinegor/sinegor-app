import { test, expect, type Page } from "@playwright/test";
import { mockApi, customerId, orderId } from "./mock-api";
import { customerApi, customerOrderId } from "./customer-api";

// Catch leaked legacy amounts/statuses even when the API still returns a price.
async function noPrice(page: Page) {
  await expect(page.locator("main")).not.toContainText(
    /стоимост|не согласован[ао]?|₽|1250[.,]50|1\s?250[.,]50/i,
  );
  await expect(page.locator('[name="agreed_price"]')).toHaveCount(0);
}

for (const width of [1440, 390]) {
  for (const price of ["1250.50", null, undefined]) {
    test(`admin order views have no price (${price}) at ${width}px`, async ({
      page,
    }, testInfo) => {
      await page.setViewportSize({ width, height: 900 });
      const state = await mockApi(page);
      state.order.agreed_price = price;
      const views = [
        ["new", `/admin/orders/new?customer_id=${customerId}`, "Новый заказ"],
        ["order", `/admin/orders/${orderId}`, "Заказ № 217"],
        ["orders", "/admin/orders", "Работа и результаты"],
        ["customer", `/admin/customers/${customerId}`, "Иван Петров"],
      ];
      for (const [name, url, heading] of views) {
        await page.goto(url);
        await expect(
          page.getByRole("heading", { name: heading, exact: true }),
        ).toBeVisible();
        await noPrice(page);
        expect(
          await page.evaluate(() => document.documentElement.scrollWidth),
        ).toBeLessThanOrEqual(width);
        if (name === "orders" || name === "customer") {
          await expect(
            page
              .getByRole("table", { name: "Заказы", exact: true })
              .getByRole("columnheader"),
          ).toHaveText(["Номер", "Услуга", "Статус", "Создан"]);
        }
        if (price === "1250.50")
          await page.screenshot({
            path: testInfo.outputPath(`${name}-${width}.png`),
            fullPage: true,
          });
      }
    });

    test(`customer order views have no price (${price}) at ${width}px`, async ({
      page,
    }, testInfo) => {
      await page.setViewportSize({ width, height: 900 });
      const state = await customerApi(page);
      state.order.agreed_price = price;
      for (const [name, url, heading] of [
        ["orders", "/customer/orders", "Мои заказы"],
        ["order", `/customer/orders/${customerOrderId}`, "Заказ № 217"],
      ]) {
        await page.goto(url);
        await expect(
          page.getByRole("heading", { name: heading, exact: true }),
        ).toBeVisible();
        await noPrice(page);
        expect(
          await page.evaluate(() => document.documentElement.scrollWidth),
        ).toBeLessThanOrEqual(width);
        if (price === "1250.50")
          await page.screenshot({
            path: testInfo.outputPath(`customer-${name}-${width}.png`),
            fullPage: true,
          });
      }
    });
  }

  test(`keyboard creates and edits an order without hidden price at ${width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    const state = await mockApi(page);
    await page.goto(`/admin/orders/new?customer_id=${customerId}`);
    const service = page.getByRole("combobox", { name: "Услуга", exact: true });
    await service.focus();
    await service.selectOption("technical_preparation");
    await page.keyboard.press("Tab");
    const create = page.getByRole("button", {
      name: "Создать заказ",
      exact: true,
    });
    await expect(create).toBeFocused();
    expect(
      await create.evaluate((el) => getComputedStyle(el).outlineStyle),
    ).not.toBe("none");
    await page.keyboard.press("Enter");
    await expect(
      page.getByRole("heading", { name: "Заказ № 217", exact: true }),
    ).toBeVisible();
    const creation = state.calls.filter(
      (c) => c.method === "POST" && c.path === "/api/admin/orders",
    );
    expect(creation).toHaveLength(1);
    expect(creation[0].body).toEqual({
      customer_id: customerId,
      service_type: "technical_preparation",
    });
    expect(creation[0].csrf).toBe("test-csrf");
    await noPrice(page);
    await service.focus();
    await service.selectOption("analysis");
    await page.keyboard.press("Tab");
    const save = page.getByRole("button", {
      name: "Сохранить условия",
      exact: true,
    });
    await expect(save).toBeFocused();
    expect(
      await save.evaluate((el) => getComputedStyle(el).outlineStyle),
    ).not.toBe("none");
    await save.screenshot({
      path: testInfo.outputPath(`keyboard-focus-${width}.png`),
    });
    await page.keyboard.press("Enter");
    await expect(
      page.getByText("Условия сохранены.", { exact: true }),
    ).toBeVisible();
    const edit = state.calls.filter(
      (c) => c.method === "PUT" && c.path.endsWith("/terms"),
    );
    expect(edit).toHaveLength(1);
    expect(edit[0].body).toEqual({ service_type: "analysis" });
    expect(edit[0].csrf).toBe("test-csrf");
    await page.reload();
    await expect(service).toHaveValue("analysis");
    await noPrice(page);
  });
}
