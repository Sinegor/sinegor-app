import { test, expect } from "@playwright/test";
import { mockApi, customerId, orderId } from "./mock-api";

const customerList = "/api/admin/customers";

test("customer search is lazy, debounced and requires explicit selection", async ({
  page,
}) => {
  const state = await mockApi(page);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/admin/orders/new");
  const picker = page.getByRole("combobox", { name: "Заказчик", exact: true });
  await expect(picker).toBeVisible();
  expect(state.calls.filter((c) => c.path === customerList)).toHaveLength(0);
  await picker.click();
  await expect(
    page.getByRole("option", {
      name: /Иван Петров.*client@example.test.*111-22-33/,
    }),
  ).toBeVisible();
  await expect(
    page.getByText("Показаны первые 100", { exact: false }),
  ).toHaveCount(0);
  await expect(page.locator('input[name="customer_id"]')).toHaveValue("");
  await page.screenshot({
    path: "/tmp/sinegor-t1101/picker-desktop.png",
    fullPage: true,
  });
  await page.clock.install();
  await picker.fill("cl");
  await page.clock.fastForward(200);
  await picker.fill("CLIENT@");
  await page.clock.fastForward(299);
  expect(state.calls.filter((c) => c.path === customerList)).toHaveLength(1);
  await page.clock.fastForward(1);
  await expect(page.getByRole("option", { name: /Иван Петров/ })).toBeVisible();
  await expect(page.locator('input[name="customer_id"]')).toHaveValue("");
  await picker.press("ArrowDown");
  await picker.press("Enter");
  await expect(page.locator('input[name="customer_id"]')).toHaveValue(
    customerId,
  );
  await expect(page.getByRole("listbox")).not.toBeVisible();
  await picker.fill("Новый запрос");
  await expect(page.locator('input[name="customer_id"]')).toHaveValue("");
  await page
    .getByRole("button", { name: "Создать заказ", exact: true })
    .click();
  expect(
    state.calls.filter(
      (c) => c.method === "POST" && c.path === "/api/admin/orders",
    ),
  ).toHaveLength(0);
});

test("chosen customer survives field validation, failed creation and revalidation", async ({
  page,
}) => {
  const state = await mockApi(page);
  await page.goto("/admin/orders/new");
  await page.getByRole("combobox", { name: "Заказчик", exact: true }).click();
  await page.getByRole("option", { name: /Иван Петров/ }).click();
  await page
    .getByLabel("Согласованная стоимость", { exact: false })
    .fill("invalid");
  await page
    .getByRole("button", { name: "Создать заказ", exact: true })
    .click();
  await expect(page.locator('input[name="customer_id"]')).toHaveValue(
    customerId,
  );
  await page.getByLabel("Согласованная стоимость", { exact: false }).fill("");
  let attempts = 0;
  await page.route("**/api/admin/orders", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    attempts++;
    if (attempts === 1)
      return route.fulfill({
        status: 422,
        json: {
          error: {
            code: "validation_error",
            message: "Request validation failed",
          },
        },
      });
    return route.fallback();
  });
  await page
    .getByRole("button", { name: "Создать заказ", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText(
    "Проверьте заполненные поля",
  );
  await expect(page.locator('input[name="customer_id"]')).toHaveValue(
    customerId,
  );
  await expect(
    page.getByRole("combobox", { name: "Заказчик", exact: true }),
  ).toHaveValue(/Иван Петров/);
  await page
    .getByRole("button", { name: "Создать заказ", exact: true })
    .click();
  await expect(page).toHaveURL(`/admin/orders/${orderId}`);
  expect(
    state.calls.find(
      (c) => c.method === "POST" && c.path === "/api/admin/orders",
    )?.body?.customer_id,
  ).toBe(customerId);
});

test("outdated search replies cannot replace newer results", async ({
  page,
}) => {
  await mockApi(page);
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let oldStarted = false;
  await page.route("**/api/admin/customers?*", async (route) => {
    const q = new URL(route.request().url()).searchParams.get("q");
    if (q !== "old" && q !== "new") return route.fallback();
    if (q === "old") {
      oldStarted = true;
      await gate;
    }
    await route.fulfill({
      json: [
        {
          id: customerId,
          display_name: q === "old" ? "Старый ответ" : "Новый ответ",
          email: "test@example.test",
          phone: null,
        },
      ],
    });
  });
  await page.goto("/admin/orders/new");
  const picker = page.getByRole("combobox", { name: "Заказчик", exact: true });
  await picker.fill("old");
  await expect.poll(() => oldStarted).toBe(true);
  await picker.fill("new");
  await expect(page.getByRole("option", { name: /Новый ответ/ })).toBeVisible();
  release();
  await expect(page.getByRole("option", { name: /Старый ответ/ })).toHaveCount(
    0,
  );
  await picker.press("ArrowDown");
  await picker.press("Enter");
  await expect(picker).toHaveValue(/Новый ответ/);
});

test("search reports empty results and failures and can be retried", async ({
  page,
}) => {
  const state = await mockApi(page);
  await page.goto("/admin/orders/new");
  const picker = page.getByRole("combobox", { name: "Заказчик", exact: true });
  await picker.fill("no match");
  await expect(page.getByRole("status")).toContainText("Заказчики не найдены");
  await page.route("**/api/admin/customers?*", (route) =>
    route.fulfill({ status: 503, json: {} }),
  );
  await picker.fill("ошибка");
  await expect(page.getByRole("alert")).toContainText("Не удалось");
  await page.unroute("**/api/admin/customers?*");
  await page.getByRole("button", { name: "Повторить поиск" }).click();
  await expect(
    page.getByText("Заказчики не найдены", { exact: false }),
  ).toBeVisible();
  await picker.fill("");
  await expect(page.getByRole("option", { name: /Иван Петров/ })).toBeVisible();
  expect(
    state.calls.filter((c) => c.path === customerList).length,
  ).toBeGreaterThan(0);
});

test("customer picker supports touch and fits a narrow screen", async ({
  browser,
}) => {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    hasTouch: true,
  });
  const page = await context.newPage();
  await mockApi(page);
  await page.goto("http://localhost:3102/admin/orders/new");
  const picker = page.getByRole("combobox", { name: "Заказчик", exact: true });
  await picker.tap();
  await page.screenshot({
    path: "/tmp/sinegor-t1101/picker-mobile.png",
    fullPage: true,
  });
  await page.getByRole("option", { name: /Иван Петров/ }).tap();
  await expect(page.locator('input[name="customer_id"]')).toHaveValue(
    customerId,
  );
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await context.close();
});

test("keyboard selection sends the chosen ID among multiple customers", async ({
  page,
}) => {
  const state = await mockApi(page);
  const secondId = "00000000-0000-0000-0000-000000000099";
  state.customers.push({
    id: secondId,
    display_name: "Другой заказчик",
    email: "second@example.test",
    phone: null,
  });
  await page.route(`**/api/admin/customers/${secondId}`, (route) =>
    route.fulfill({ json: state.customers[1] }),
  );
  await page.goto("/admin/orders/new");
  const picker = page.getByRole("combobox", { name: "Заказчик", exact: true });
  await picker.focus();
  await picker.press("ArrowDown");
  await expect(page.getByRole("listbox").getByRole("option")).toHaveCount(2);
  await picker.press("End");
  await picker.press("Enter");
  await expect(picker).toHaveValue(/Другой заказчик/);
  await page
    .getByRole("button", { name: "Создать заказ", exact: true })
    .click();
  await expect(page).toHaveURL(`/admin/orders/${orderId}`);
  await expect(
    page.getByRole("heading", { name: "Заказ № 217", exact: true }),
  ).toBeVisible();
  expect(
    state.calls.find(
      (c) => c.path === "/api/admin/orders" && c.method === "POST",
    )?.body?.customer_id,
  ).toBe(secondId);
});

test("customer search returns to admin login when the session expires", async ({
  page,
}) => {
  const state = await mockApi(page);
  await page.goto("/admin/orders/new");
  const picker = page.getByRole("combobox", { name: "Заказчик", exact: true });
  await expect(picker).toBeVisible();
  state.authenticated = false;
  await picker.click();
  await expect(page).toHaveURL("/auth/admin");
});
