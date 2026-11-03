import { test, expect } from "@playwright/test";
import { mockApi, customerId } from "./mock-api";
import { customerApi, customerOrderId } from "./customer-api";

for (const role of ["admin", "customer"] as const) {
  const destination =
    role === "admin" ? "/admin/customers" : "/customer/orders";
  const detail =
    role === "admin"
      ? `/admin/customers/${customerId}`
      : `/customer/orders/${customerOrderId}`;
  const heading = role === "admin" ? "Контакты и заказы" : "Мои заказы";
  const login = role === "admin" ? "/auth/admin" : "/auth/login";
  const sensitive =
    role === "admin" ? "Иван Петров" : "Согласованный анализ документов";
  const setup = role === "admin" ? mockApi : customerApi;

  test(`${role}: public navigation and either login reuse the active session`, async ({
    page,
  }) => {
    const state = await setup(page);
    await page.goto(destination);
    await expect(
      page.getByRole("heading", { name: heading, exact: true }),
    ).toBeVisible();
    await page.getByRole("link", { name: /SINEGOR LAB/ }).click();
    await page.getByRole("link", { name: "Документы", exact: true }).click();
    for (const label of ["Вход заказчика", "Вход администратора"]) {
      await page.getByRole("link", { name: label, exact: true }).click();
      await expect(page).toHaveURL(destination);
      await expect(
        page.getByRole("heading", { name: heading, exact: true }),
      ).toBeVisible();
      await page.getByRole("link", { name: /SINEGOR LAB/ }).click();
    }
    for (const path of ["/auth/login", "/auth/admin"]) {
      await page.goto(path);
      await expect(page).toHaveURL(destination);
    }
    expect(state.calls.some((call) => call.method === "POST")).toBe(false);
  });

  test(`${role}: logout blocks private history and direct reload`, async ({
    page,
  }) => {
    await setup(page);
    await page.goto(destination);
    await expect(
      page.getByRole("heading", { name: heading, exact: true }),
    ).toBeVisible();
    await page.goto(detail);
    await expect(
      page.getByText(sensitive, { exact: true }).first(),
    ).toBeVisible();
    await page.getByRole("button", { name: "Выйти", exact: true }).click();
    await expect(page).toHaveURL(login);
    for (let i = 0; i < 2; i++) {
      await page.goBack();
      await expect(page).toHaveURL(login);
      await expect(page.getByText(sensitive, { exact: true })).toHaveCount(0);
    }
    await page.goto(detail);
    await expect(page).toHaveURL(login);
    await page.reload();
    await expect(page.getByText(sensitive, { exact: true })).toHaveCount(0);
  });

  test(`${role}: a frozen private document is hidden and rechecks the session on restore`, async ({
    page,
  }) => {
    const state = await setup(page);
    await page.goto(detail);
    const content = page.getByText(sensitive, { exact: true }).first();
    await expect(content).toBeVisible();
    // Exercise the lifecycle even on engines that evict no-store documents from bfcache.
    await page.evaluate(() =>
      window.dispatchEvent(
        new PageTransitionEvent("pagehide", { persisted: true }),
      ),
    );
    await expect(content).toBeHidden();
    state.authenticated = false;
    await page.evaluate(() =>
      window.dispatchEvent(
        new PageTransitionEvent("pageshow", { persisted: true }),
      ),
    );
    await expect(page).toHaveURL(login);
    await expect(page.getByText(sensitive, { exact: true })).toHaveCount(0);
  });

  test(`${role}: a restored document with a valid session loads private data again`, async ({
    page,
  }) => {
    await setup(page);
    await page.goto(detail);
    const content = page.getByText(sensitive, { exact: true }).first();
    await expect(content).toBeVisible();
    await page.evaluate(() =>
      window.dispatchEvent(
        new PageTransitionEvent("pagehide", { persisted: true }),
      ),
    );
    await expect(content).toBeHidden();
    await page.evaluate(() =>
      window.dispatchEvent(
        new PageTransitionEvent("pageshow", { persisted: true }),
      ),
    );
    await expect(content).toBeVisible();
    await expect(page).toHaveURL(detail);
  });

  test(`${role}: an expired session shows login and cannot reopen private data`, async ({
    page,
  }) => {
    const state = await setup(page);
    await page.goto(detail);
    await expect(
      page.getByText(sensitive, { exact: true }).first(),
    ).toBeVisible();
    state.authenticated = false;
    await page.getByRole("link", { name: /SINEGOR LAB/ }).click();
    await page
      .getByRole("link", {
        name: role === "admin" ? "Вход администратора" : "Вход заказчика",
        exact: true,
      })
      .click();
    await expect(page).toHaveURL(login);
    await expect(
      page.getByLabel(role === "admin" ? "Email администратора" : "Ваш email", {
        exact: true,
      }),
    ).toBeVisible();
    await page.goto(detail);
    await expect(page).toHaveURL(login);
    await expect(page.getByText(sensitive, { exact: true })).toHaveCount(0);
  });

  test(`${role}: session service failure does not masquerade as anonymous login`, async ({
    page,
  }) => {
    const state = await setup(page);
    await page.route("**/api/auth/session", (route) =>
      route.fulfill({ status: 503, json: {} }),
    );
    await page.goto(login);
    await expect(
      page.getByRole("heading", {
        name: "Не удалось открыть страницу",
        exact: true,
      }),
    ).toBeVisible();
    await expect(page.getByRole("textbox")).toHaveCount(0);
    expect(state.calls.some((call) => call.method === "POST")).toBe(false);
  });

  test(`${role}: mobile navigation reuses the session and logout blocks history`, async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await setup(page);
    await page.goto("/");
    await page
      .getByRole("button", { name: "Открыть меню", exact: true })
      .click();
    await page
      .getByRole("link", {
        name: role === "admin" ? "Вход администратора" : "Вход заказчика",
        exact: true,
      })
      .click();
    await expect(page).toHaveURL(destination);
    await expect(
      page.getByRole("heading", { name: heading, exact: true }),
    ).toBeVisible();
    await page
      .getByRole("button", {
        name: role === "admin" ? "Открыть разделы" : "Открыть меню кабинета",
        exact: true,
      })
      .click();
    await page.getByRole("button", { name: "Выйти", exact: true }).click();
    await expect(page).toHaveURL(login);
    await page.goBack();
    await expect(page).toHaveURL(login);
    await expect(page.getByText(sensitive, { exact: true })).toHaveCount(0);
  });
}
