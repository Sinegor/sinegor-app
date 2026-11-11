import { test, expect } from "@playwright/test";
import { mockApi, customerId } from "./mock-api";

for (const width of [1440, 390]) {
  for (const editing of [false, true]) {
    test(`customer name required for ${editing ? "legacy edit" : "creation"} at ${width}px`, async ({
      page,
    }) => {
      const state = await mockApi(page);
      state.customers[0].display_name = null;
      await page.setViewportSize({ width, height: 900 });
      await page.goto(
        editing ? `/admin/customers/${customerId}` : "/admin/customers/new",
      );
      const email = page.getByLabel("Email", { exact: true });
      const name = page.getByLabel("ФИО заказчика", { exact: true });
      const submit = page.getByRole("button", {
        name: editing ? "Сохранить карточку" : "Создать и пригласить",
        exact: true,
      });
      await expect(name).toBeVisible();
      await expect(name).toHaveAttribute("required", "");
      if (!editing) await email.fill("new@example.test");
      else {
        await expect(
          page.getByRole("link", { name: "№ 217", exact: true }),
        ).toBeVisible();
        await page
          .getByRole("button", { name: "Повторить приглашение", exact: true })
          .click();
        await expect(
          page.getByText("Приглашение передано почтовому сервису.", {
            exact: true,
          }),
        ).toBeVisible();
        await page.getByLabel("Телефон", { exact: true }).fill("+7 999");
      }
      for (const blank of ["", "   ", "\u00a0\u2003"]) {
        await name.fill(blank);
        await submit.click();
        await expect(name).toHaveJSProperty(
          "validationMessage",
          "Укажите ФИО заказчика.",
        );
        expect(
          state.calls.filter(
            (c) =>
              c.path ===
                (editing
                  ? `/api/admin/customers/${customerId}`
                  : "/api/admin/customers") &&
              c.method === (editing ? "PATCH" : "POST"),
          ),
        ).toHaveLength(0);
        expect(state.customers[0].display_name).toBeNull();
      }
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await page.screenshot({
        path: `/tmp/sinegor-name-${editing ? "edit" : "new"}-${width}-invalid.png`,
        fullPage: true,
      });
      await name.fill("Иван Петров");
      await expect(name).toHaveJSProperty("validationMessage", "");
      await submit.click();
      if (editing)
        await expect(
          page.getByText("Карточка сохранена.", { exact: true }),
        ).toBeVisible();
      else await expect(page).toHaveURL(`/admin/customers/${customerId}`);
      expect(state.customers[0].display_name).toBe("Иван Петров");
      await page.screenshot({
        path: `/tmp/sinegor-name-${editing ? "edit" : "new"}-${width}-saved.png`,
        fullPage: true,
      });
    });
  }
}

test("customer creation keeps required email and format validation", async ({
  page,
}) => {
  const state = await mockApi(page);
  await page.goto("/admin/customers/new");
  await page.getByLabel("ФИО заказчика", { exact: true }).fill("Иван Петров");
  const email = page.getByLabel("Email", { exact: true });
  const submit = page.getByRole("button", {
    name: "Создать и пригласить",
    exact: true,
  });
  await submit.click();
  await expect(email).toHaveJSProperty(
    "validationMessage",
    "Заполните это поле.",
  );
  await email.fill("invalid");
  await submit.click();
  await expect(email).toHaveJSProperty(
    "validationMessage",
    "Укажите корректный email.",
  );
  expect(
    state.calls.filter(
      (c) => c.method === "POST" && c.path === "/api/admin/customers",
    ),
  ).toHaveLength(0);
});

test("a filled customer name cannot be cleared", async ({ page }) => {
  const state = await mockApi(page);
  await page.goto(`/admin/customers/${customerId}`);
  await page.getByLabel("ФИО заказчика", { exact: true }).fill("   ");
  await page
    .getByRole("button", { name: "Сохранить карточку", exact: true })
    .click();
  expect(state.calls.filter((c) => c.method === "PATCH")).toHaveLength(0);
  expect(state.customers[0].display_name).toBe("Иван Петров");
});

for (const status of [409, 422]) {
  test(`customer form displays safe API error ${status}`, async ({ page }) => {
    const state = await mockApi(page);
    await page.route("**/api/admin/customers", (route) =>
      route.request().method() === "POST"
        ? route.fulfill({
            status,
            json: {
              error: {
                code: status === 422 ? "customer_name_invalid" : "http_409",
                message: "private server text",
              },
            },
          })
        : route.fallback(),
    );
    await page.goto("/admin/customers/new");
    await page.getByLabel("Email", { exact: true }).fill("client@example.test");
    await page.getByLabel("ФИО заказчика", { exact: true }).fill("Иван Петров");
    await page
      .getByRole("button", { name: "Создать и пригласить", exact: true })
      .click();
    await expect(page.getByRole("alert")).toContainText(
      status === 422
        ? "Укажите ФИО заказчика"
        : "Данные или условия операции изменились",
    );
    expect(state.customers[0].email).toBe("client@example.test");
    await expect(page).toHaveURL("/admin/customers/new");
    await expect(page.getByText("private server text")).toHaveCount(0);
  });
}
