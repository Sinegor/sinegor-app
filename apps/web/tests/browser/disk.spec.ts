import { test, expect } from "@playwright/test";
import { mockApi, orderId } from "./mock-api";

for (const base of ["", "Финансовые документы"]) {
  test(`folder creation sends optional name base: ${base || "default"}`, async ({
    page,
  }) => {
    const state = await mockApi(page);
    await page.goto(`/admin/orders/${orderId}`);
    await page.getByLabel("Основа имени папки", { exact: false }).fill(base);
    await page
      .getByRole("button", { name: "Создать папку заказа", exact: true })
      .click();
    await expect(
      page.getByText("Папка создана и привязана.", { exact: true }),
    ).toBeVisible();
    expect(
      state.calls.find(
        (c) => c.method === "POST" && c.path.endsWith("/folder"),
      )!.body,
    ).toEqual({ name_base: base });
  });
}

for (const [status, code, message] of [
  [422, "disk_invalid_path", "Проверьте путь"],
  [404, "disk_folder_not_found", "Папка не найдена"],
  [503, "disk_access_denied", "Диска недостаточно прав"],
  [503, "disk_unavailable", "Яндекс Диск временно недоступен"],
] as const) {
  test(`binding failure ${code} is visible and preserves input`, async ({
    page,
  }) => {
    await mockApi(page);
    await page.route(`**/api/admin/orders/${orderId}/folder`, async (route) => {
      if (route.request().method() !== "PUT") return route.fallback();
      return route.fulfill({
        status,
        json: { error: { code, message: "private upstream details" } },
      });
    });
    await page.goto(`/admin/orders/${orderId}`);
    await page
      .getByLabel("Путь существующей папки")
      .fill("disk:/SINEGOR/orders/example");
    await page
      .getByLabel("Я проверил принадлежность папки этому заказу")
      .check();
    await page
      .getByRole("button", {
        name: "Привязать существующую папку",
        exact: true,
      })
      .click();
    await expect(page.getByRole("alert")).toContainText(message);
    await expect(page.getByLabel("Путь существующей папки")).toHaveValue(
      "disk:/SINEGOR/orders/example",
    );
    await expect(
      page.getByText("Папка проверена и привязана.", { exact: true }),
    ).toHaveCount(0);
    await expect(page.getByText("private upstream details")).toHaveCount(0);
  });
}

test("folder conflict preserves base and never claims successful creation", async ({
  page,
}) => {
  await mockApi(page);
  await page.route(`**/api/admin/orders/${orderId}/folder`, async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    return route.fulfill({
      status: 409,
      json: { error: { code: "disk_name_conflict" } },
    });
  });
  await page.goto(`/admin/orders/${orderId}`);
  await page
    .getByLabel("Основа имени папки", { exact: false })
    .fill("Документы");
  await page
    .getByRole("button", { name: "Создать папку заказа", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText(
    "таким именем уже существует",
  );
  await expect(
    page.getByLabel("Основа имени папки", { exact: false }),
  ).toHaveValue("Документы");
  await expect(
    page.getByText("Папка создана и привязана.", { exact: true }),
  ).toHaveCount(0);
});
