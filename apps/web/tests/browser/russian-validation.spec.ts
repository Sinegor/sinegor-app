import { test, expect } from "@playwright/test";
import { mockApi, agreement, orderId } from "./mock-api";

test("native required and email validation messages are Russian", async ({
  page,
}) => {
  const state = await mockApi(page);
  state.authenticated = false;
  await page.goto("/auth/admin");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  const email = page.getByLabel("Email администратора");
  await expect(email).toHaveJSProperty(
    "validationMessage",
    "Заполните это поле.",
  );
  await email.fill("invalid");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(email).toHaveJSProperty(
    "validationMessage",
    "Укажите корректный email.",
  );
  await email.fill("admin@example.test");
  await expect(email).toHaveJSProperty("validationMessage", "");
});

test("approval disables rejection reason and never sends a previous reason", async ({
  page,
}) => {
  const state = await mockApi(page);
  state.agreement = agreement();
  await page.goto(`/admin/orders/${orderId}`);
  await page
    .getByRole("button", { name: "Скачать PDF заказчика", exact: true })
    .click();
  await page
    .getByLabel("Я проверил документ и подписи", { exact: false })
    .check();
  const reason = page.getByLabel("Причина отклонения", { exact: true });
  await expect(reason).toBeDisabled();
  await page
    .getByRole("combobox", { name: "Решение", exact: true })
    .selectOption("reject");
  await expect(reason).toBeEnabled();
  await page.getByRole("button", { name: "Продолжить", exact: true }).click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await reason.fill("   ");
  await page.getByRole("button", { name: "Продолжить", exact: true }).click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await reason.fill("Подпишите документ");
  await page
    .getByRole("combobox", { name: "Решение", exact: true })
    .selectOption("approve");
  await expect(reason).toBeDisabled();
  await page.getByRole("button", { name: "Продолжить", exact: true }).click();
  await page
    .getByRole("button", { name: "Утвердить версию", exact: true })
    .click();
  await expect(
    page.getByText("Соглашение утверждено.", { exact: true }),
  ).toBeVisible();
  expect(
    state.calls.find((c) => c.path.endsWith("/agreement/approve"))?.body,
  ).toEqual({ revision: 2 });
});
