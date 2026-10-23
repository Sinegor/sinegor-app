import { test, expect } from "@playwright/test";
import { mockApi, customerId, orderId } from "./mock-api";
import { customerApi } from "./customer-api";

test.use({ viewport: { width: 390, height: 844 } });

test("mobile admin sections support keyboard dismissal and route navigation", async ({
  page,
}) => {
  await mockApi(page);
  await page.goto("/admin/customers");
  const toggle = page.getByRole("button", { name: "Открыть разделы" });
  await toggle.click();
  const menu = page.getByRole("dialog", { name: "Разделы" });
  await expect(menu).toBeVisible();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(
    menu.getByRole("link", { name: "Заказчики", exact: true }),
  ).toHaveAttribute("aria-current", "page");
  await page.keyboard.press("Escape");
  await expect(menu).not.toBeVisible();
  await expect(toggle).toBeFocused();
  await toggle.click();
  await menu.getByRole("link", { name: "Заказы", exact: true }).click();
  await expect(page).toHaveURL(/\/admin\/orders$/);
  await expect(menu).not.toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Работа и результаты" }),
  ).toBeVisible();
});

test("resizing an open mobile menu restores usable desktop navigation", async ({
  page,
}) => {
  await mockApi(page);
  await page.goto("/admin/customers");
  await page.getByRole("button", { name: "Открыть разделы" }).click();
  await expect(page.getByRole("dialog", { name: "Разделы" })).toBeVisible();
  await page.setViewportSize({ width: 1440, height: 1000 });
  await expect(page.getByRole("dialog", { name: "Разделы" })).not.toBeVisible();
  await expect(
    page.getByRole("button", { name: "Открыть разделы" }),
  ).not.toBeVisible();
  await page
    .getByRole("navigation", { name: "Разделы администратора" })
    .getByRole("link", { name: "Заказы", exact: true })
    .click();
  await expect(page).toHaveURL(/\/admin\/orders$/);
});

test("customer mobile menu keeps email, own orders and authenticated logout", async ({
  page,
}) => {
  const state = await customerApi(page);
  await page.goto("/customer/orders");
  await page.getByRole("button", { name: "Открыть меню кабинета" }).click();
  const menu = page.getByRole("dialog", { name: "Личный кабинет" });
  await expect(
    menu.getByText("client@example.test", { exact: true }),
  ).toBeVisible();
  await expect(
    menu.getByRole("link", { name: "Мои заказы", exact: true }),
  ).toBeVisible();
  await menu.getByRole("button", { name: "Выйти", exact: true }).click();
  await expect(page).toHaveURL(/\/auth\/login$/);
  expect(state.calls.find((call) => call.path.endsWith("/logout"))?.csrf).toBe(
    "customer-csrf",
  );
});

test("public mobile menu exposes both existing login routes", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Открыть меню" }).click();
  const menu = page.getByRole("dialog", { name: "Навигация SINEGOR LAB" });
  await expect(
    menu.getByRole("link", { name: "Вход заказчика" }),
  ).toHaveAttribute("href", "/auth/login");
  await menu.getByRole("link", { name: "Вход администратора" }).click();
  await expect(
    page.getByRole("heading", { name: "Вход администратора" }),
  ).toBeVisible();
  await expect(menu).not.toBeVisible();
});

test("empty customer search explains the query and keeps reset available", async ({
  page,
}) => {
  await mockApi(page);
  await page.goto("/admin/customers?q=nonexistent");
  await expect(
    page.getByText("По вашему запросу заказчики не найдены.", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByLabel("Поиск по имени, email или телефону"),
  ).toHaveValue("nonexistent");
  await page.getByRole("link", { name: "Сбросить", exact: true }).click();
  await expect(
    page.getByRole("link", { name: "Иван Петров", exact: true }),
  ).toBeVisible();
});

test("history table keeps readable columns with scrolling inside its region", async ({
  page,
}) => {
  await mockApi(page);
  await page.goto(`/admin/customers/${customerId}`);
  const region = page.getByRole("region", { name: "Заказы", exact: true });
  const header = region.getByRole("columnheader", {
    name: "Номер",
    exact: true,
  });
  await expect(header).toBeVisible();
  expect((await header.boundingBox())!.height).toBeLessThan(80);
  expect(await region.evaluate((el) => el.scrollWidth > el.clientWidth)).toBe(
    true,
  );
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

for (const role of ["admin", "customer"] as const) {
  test(`failed ${role} logout is explained inside the active mobile menu`, async ({
    page,
  }) => {
    if (role === "admin") await mockApi(page);
    else await customerApi(page);
    await page.route("**/api/auth/logout", (route) =>
      route.fulfill({ status: 503, json: {} }),
    );
    await page.goto(role === "admin" ? "/admin/customers" : "/customer/orders");
    await page
      .getByRole("button", {
        name: role === "admin" ? "Открыть разделы" : "Открыть меню кабинета",
      })
      .click();
    const menu = page.getByRole("dialog", {
      name: role === "admin" ? "Разделы" : "Личный кабинет",
    });
    await menu.getByRole("button", { name: "Выйти", exact: true }).click();
    await expect(menu.getByRole("alert")).toContainText(
      "Не удалось выполнить запрос",
    );
    await expect(
      menu.getByRole("button", { name: "Выйти", exact: true }),
    ).toBeEnabled();
  });
}

test("opening a dangerous dialog gives initial keyboard focus to its title", async ({
  page,
}) => {
  const state = await mockApi(page);
  await page.goto(`/admin/orders/${orderId}`);
  await page
    .getByRole("button", { name: "Отменить заказ", exact: true })
    .click();
  const dialog = page.getByRole("dialog", { name: /Отменить заказ №/ });
  await expect(dialog.getByRole("heading")).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(dialog).toBeVisible();
  expect(
    state.calls.some(
      (call) => call.method === "POST" && call.path.endsWith("/status"),
    ),
  ).toBe(false);
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
});

for (const section of ["customers", "orders"] as const) {
  test(`empty later ${section} page is identified as an empty pagination page`, async ({
    page,
  }) => {
    const state = await mockApi(page);
    state.customers = [];
    await page.route("**/api/admin/orders?*", (route) =>
      route.fulfill({ status: 200, json: [] }),
    );
    await page.goto(`/admin/${section}?offset=25`);
    await expect(
      page.getByText(
        section === "customers"
          ? "На этой странице нет заказчиков."
          : "На этой странице нет заказов.",
        { exact: true },
      ),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: "Назад", exact: true }),
    ).toBeVisible();
  });
}
