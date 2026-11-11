import { test, expect } from "@playwright/test";
import { mockApi, folder, deletion, customerId, orderId } from "./mock-api";

test("saving one customer field preserves parallel contact changes", async ({
  page,
}) => {
  const state = await mockApi(page);
  await page.goto(`/admin/customers/${customerId}`);
  await expect(
    page.getByRole("heading", { name: "Иван Петров", exact: true }),
  ).toBeVisible();

  // A second tab saved contact changes after this tab loaded the customer.
  state.customers[0].email = "updated@example.test";
  state.customers[0].phone = "+7 999 222-33-44";
  await page.getByLabel("ФИО заказчика").fill("Новое имя");
  await page
    .getByRole("button", { name: "Сохранить карточку", exact: true })
    .click();
  await expect(
    page.getByText("Карточка сохранена.", { exact: true }),
  ).toBeVisible();

  expect(state.calls.find((call) => call.method === "PATCH")!.body).toEqual({
    display_name: "Новое имя",
  });
  expect(state.customers[0].email).toBe("updated@example.test");
  expect(state.customers[0].phone).toBe("+7 999 222-33-44");
  await expect(page.getByLabel("Email", { exact: true })).toHaveValue(
    "updated@example.test",
  );
});

test("customer patch includes explicit email changes and nullable clearing only", async ({
  page,
}) => {
  const state = await mockApi(page);
  // Existing names may contain whitespace; untouched fields must remain untouched.
  state.customers[0].display_name = " Иван Петров ";
  await page.goto(`/admin/customers/${customerId}`);
  await page.getByLabel("Email", { exact: true }).fill("changed@example.test");
  await page.getByLabel("Телефон", { exact: true }).fill("");
  await page
    .getByRole("button", { name: "Сохранить карточку", exact: true })
    .click();
  await expect(
    page.getByText("Карточка сохранена.", { exact: true }),
  ).toBeVisible();

  expect(state.calls.find((call) => call.method === "PATCH")!.body).toEqual({
    email: "changed@example.test",
    phone: null,
  });
  expect(state.customers[0].display_name).toBe(" Иван Петров ");
});

test("reset and browser history keep the customer search field in sync", async ({
  page,
}) => {
  const state = await mockApi(page);
  state.customers.push({
    id: "00000000-0000-0000-0000-000000000004",
    email: "other@example.test",
    display_name: "Другой заказчик",
    phone: null,
    blocked_at: null,
    block_reason: null,
    block_comment: null,
  });
  await page.goto("/admin/customers");
  const search = page.getByLabel("Поиск по имени, email или телефону");
  await search.fill("Иван");
  await page.getByRole("button", { name: "Найти", exact: true }).click();
  await expect(page).toHaveURL(/q=/);
  await expect(
    page.getByRole("link", { name: "Другой заказчик", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("link", { name: "Сбросить", exact: true }).click();
  await expect(
    page.getByRole("link", { name: "Другой заказчик", exact: true }),
  ).toBeVisible();
  await expect(search).toHaveValue("");

  await page.goBack();
  await expect(search).toHaveValue("Иван");
  await expect(
    page.getByRole("link", { name: "Другой заказчик", exact: true }),
  ).toHaveCount(0);
  await page.goForward();
  await expect(search).toHaveValue("");
  await expect(
    page.getByRole("link", { name: "Другой заказчик", exact: true }),
  ).toBeVisible();
  await search.fill("Черновик");
  await page.getByRole("link", { name: "Сбросить", exact: true }).click();
  await expect(search).toHaveValue("");
});

test("uncertain deletion keeps manual Disk access without enabling folder edits", async ({
  page,
}) => {
  const state = await mockApi(page);
  state.order.status = "completed";
  state.folder = folder();
  state.folder.deletion_started_at = "2026-10-01T10:00:00Z";
  state.deletion = deletion();
  state.deletion.status = "error";
  await page.goto(`/admin/orders/${orderId}`);

  await expect(
    page.getByRole("button", {
      name: "Сохранить клиентскую ссылку",
      exact: true,
    }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", {
      name: "Проверить существующую привязку",
      exact: true,
    }),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "Получить ссылку для открытия", exact: true })
    .click();
  await expect(
    page.getByRole("link", { name: "Открыть папку на Диске", exact: false }),
  ).toHaveAttribute(
    "href",
    "https://disk.yandex.ru/client/disk/SINEGOR/orders/order-217",
  );
  expect(state.deleteCount).toBe(0);
});

for (const blocked of ["operation", "deleted"] as const) {
  test(`previously obtained Disk link is hidden when folder is ${blocked}`, async ({
    page,
  }) => {
    const state = await mockApi(page);
    state.folder = folder();
    await page.goto(`/admin/orders/${orderId}`);
    await page
      .getByRole("button", {
        name: "Получить ссылку для открытия",
        exact: true,
      })
      .click();
    const link = page.getByRole("link", {
      name: "Открыть папку на Диске",
      exact: false,
    });
    await expect(link).toBeVisible();

    state.folder.deletion_started_at = "2026-10-01T10:00:00Z";
    if (blocked === "operation")
      state.folder.deletion_operation_id = "operation-1";
    else state.folder.deleted_at = "2026-10-01T10:00:00Z";
    await page
      .getByRole("button", { name: "Обновить карточку", exact: true })
      .click();
    await expect(
      page.getByRole("button", {
        name: "Получить ссылку для открытия",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(link).toHaveCount(0);
  });
}
