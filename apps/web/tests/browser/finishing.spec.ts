import { test, expect } from "@playwright/test";
import { mockApi, customerId, orderId } from "./mock-api";
import { customerApi, customerOrderId } from "./customer-api";

test("a missing CMS presentation keeps the layout without a broken download link", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.locator(".hero-video").getByRole("status")).toContainText(
    "Видеопрезентация пока недоступна",
  );
  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(page.locator("video source")).toHaveCount(0);
  await expect(
    page.getByRole("link", { name: "Открыть видео отдельно" }),
  ).toHaveCount(0);
  await expect(page.locator(".hero-video")).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Запросить консультацию", exact: true }),
  ).toBeVisible();
});

for (const width of [1440, 1024, 768, 390, 320]) {
  test(`working interfaces fit ${width}px with long customer data`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    const state = await mockApi(page);
    state.customers[0].display_name =
      "Заказчик с длинным наименованием организации ".repeat(4);
    state.customers[0].email = `${"a".repeat(64)}@${"subdomain.".repeat(8)}example.test`;
    state.order.description =
      "Описание согласованного исследования юридических документов. ".repeat(
        30,
      );
    for (const [name, path] of [
      ["customers", "/admin/customers"],
      ["customer-new", "/admin/customers/new"],
      ["customer", `/admin/customers/${customerId}`],
      ["orders", "/admin/orders"],
      ["order-new", `/admin/orders/new?customer_id=${customerId}`],
      ["order", `/admin/orders/${orderId}`],
    ]) {
      await page.goto(path);
      await expect(page.locator("h1")).toBeVisible();
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth),
      ).toBeLessThanOrEqual(width);
      if (name === "customers" && width <= 390) {
        const table = page.getByRole("region", { name: "Заказчики" });
        expect(
          await table.evaluate((el) => el.scrollWidth > el.clientWidth),
        ).toBe(true);
        expect(
          (await table.getByRole("cell").first().boundingBox())!.width,
        ).toBeGreaterThanOrEqual(160);
      }
      await page.screenshot({
        path: `/tmp/sinegor-f6/${width}-${name}.png`,
        fullPage: true,
        animations: "disabled",
      });
    }
    await page
      .getByRole("button", { name: "Отменить заказ", exact: true })
      .click();
    const dialog = page.getByRole("dialog", { name: /Отменить заказ №/ });
    await expect(dialog).toBeVisible();
    const bounds = (await dialog.boundingBox())!;
    expect(bounds.x).toBeGreaterThanOrEqual(0);
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(width);
    await page.screenshot({
      path: `/tmp/sinegor-f6/${width}-confirmation.png`,
      animations: "disabled",
    });
    await page.keyboard.press("Escape");

    const customer = await customerApi(page);
    customer.order.description = state.order.description;
    for (const [name, path] of [
      ["my-orders", "/customer/orders"],
      ["my-order", `/customer/orders/${customerOrderId}`],
    ]) {
      await page.goto(path);
      await expect(page.locator("h1")).toBeVisible();
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth),
      ).toBeLessThanOrEqual(width);
      await page.screenshot({
        path: `/tmp/sinegor-f6/${width}-${name}.png`,
        fullPage: true,
        animations: "disabled",
      });
    }
  });
}

test("loading and empty states remain usable with reduced motion", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  const state = await mockApi(page);
  let release!: () => void;
  const gate = new Promise<void>((resolve) => (release = resolve));
  await page.route("**/api/auth/session", async (route) => {
    await gate;
    await route.fallback();
  });
  try {
    await page.goto("/admin/customers");
    const loading = page.getByRole("status");
    await expect(loading).toContainText("Загрузка административной панели");
    expect(
      await page
        .locator(".loading-spinner")
        .evaluate((el) => getComputedStyle(el).animationName),
    ).toBe("none");
    await page.screenshot({ path: "/tmp/sinegor-f6/loading.png" });
  } finally {
    release();
  }
  await expect(page.locator("h1")).toHaveText("Контакты и заказы");
  state.customers = [];
  await page.reload();
  await expect(
    page.getByText("Заказчиков пока нет. Создайте первую карточку.", {
      exact: true,
    }),
  ).toBeVisible();
  await page.screenshot({ path: "/tmp/sinegor-f6/empty.png" });
});

test("a pending operation shows progress, preserves the form and then confirms success", async ({
  page,
}) => {
  const state = await mockApi(page);
  await page.goto(`/admin/customers/${customerId}`);
  let release!: () => void;
  state.mutationGate = new Promise<void>((resolve) => (release = resolve));
  const submit = page.getByRole("button", { name: "Сохранить карточку" });
  const before = (await submit.boundingBox())!;
  try {
    await page.getByLabel("ФИО заказчика").fill("Обновлённое имя");
    await submit.click();
    await expect(page.getByRole("status")).toContainText("Выполняется");
    await expect(submit).toBeDisabled();
    await expect(page.getByLabel("ФИО заказчика")).toHaveValue(
      "Обновлённое имя",
    );
    expect((await submit.boundingBox())!.width).toBe(before.width);
  } finally {
    release();
  }
  await expect(page.getByRole("status")).toContainText("Карточка сохранена");
  await expect(submit).toBeEnabled();
  expect(state.calls.filter((call) => call.method === "PATCH")).toHaveLength(1);
});

for (const width of [1440, 390]) {
  test(`public, authentication and error states fit ${width}px`, async ({
    page,
  }) => {
    await page.route("**/api/auth/session", (route) =>
      route.fulfill({ status: 401, json: {} }),
    );
    await page.setViewportSize({ width, height: 900 });
    for (const [name, path] of [
      ["home", "/"],
      ["analysis", "/services/ai-analysis"],
      ["technical", "/services/technical"],
      ["about", "/about"],
      ["publications", "/publications"],
      ["contacts", "/contacts"],
      ["login", "/auth/login"],
      ["admin-login", "/auth/admin"],
      ["invalid-link", "/auth/magic-link"],
      ["404", "/missing"],
    ]) {
      await page.goto(path);
      await expect(page.locator("h1")).toBeVisible();
      if (name === "invalid-link")
        await expect(page.getByRole("alert")).toBeVisible();
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth),
      ).toBeLessThanOrEqual(width);
      await page.screenshot({
        path: `/tmp/sinegor-f6/${width}-${name}.png`,
        fullPage: true,
        animations: "disabled",
      });
    }
    await mockApi(page);
    await page.route("**/api/admin/customers?*", (route) =>
      route.fulfill({ status: 503, json: {} }),
    );
    await page.goto("/admin/customers");
    await expect(page.getByRole("alert")).toContainText(
      "Не удалось выполнить запрос",
    );
    await expect(
      page.getByRole("button", { name: "Повторить загрузку" }),
    ).toBeEnabled();
    await page.screenshot({
      path: `/tmp/sinegor-f6/${width}-admin-error.png`,
      fullPage: true,
      animations: "disabled",
    });
    await customerApi(page);
    await page.route("**/api/customer/orders", (route) =>
      route.fulfill({ status: 503, json: {} }),
    );
    await page.goto("/customer/orders");
    await expect(page.getByRole("alert")).toContainText(
      "Не удалось выполнить запрос",
    );
    await expect(
      page.getByRole("button", { name: "Повторить загрузку" }),
    ).toBeEnabled();
    await page.screenshot({
      path: `/tmp/sinegor-f6/${width}-customer-error.png`,
      fullPage: true,
      animations: "disabled",
    });
  });
}
