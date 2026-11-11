import { test, expect } from "@playwright/test";
import { mockApi } from "./mock-api";

const id = "40000000-0000-4000-8000-000000000001";
const kinds = [
  "disk_folder",
  "consultation_auto",
  "consultation_manual",
  "security_events",
  "customer_fields",
  "agreement",
  "order_history",
  "customer",
];
const ready = {
  id,
  kind: "disk_folder",
  state: "ready",
  subject: "Иван Петров — заказ № 217",
  created_at: "2026-11-05T21:30:00Z",
  destroyed_at: "2026-11-05T22:30:00Z",
  expires_at: "2029-11-05T22:30:00Z",
  error_code: null,
  act_url: `/api/admin/destructions/${id}/documents/act`,
  extract_url: `/api/admin/destructions/${id}/documents/extract`,
  metadata_json: {},
};

for (const width of [1440, 390]) {
  test(`destruction register searches all eight operations and prints paired PDFs ${width}`, async ({
    page,
  }, info) => {
    await page.setViewportSize({ width, height: 900 });
    await mockApi(page);
    const queries: URLSearchParams[] = [];
    await page.route("**/api/admin/destructions**", async (route) => {
      const url = new URL(route.request().url());
      queries.push(url.searchParams);
      return route.fulfill({
        json: url.searchParams.get("q")
          ? []
          : kinds.map((kind, i) => ({
              ...ready,
              id: `${id.slice(0, -1)}${i + 1}`,
              kind,
            })),
      });
    });
    await page.goto("/admin/destructions");
    await expect(
      page.getByRole("heading", { name: "Реестр уничтожения", exact: true }),
    ).toBeVisible();
    await expect(page.getByRole("heading", { level: 2 })).toHaveCount(8);
    const card = page.locator("section.card").first();
    await expect(
      card.getByText("Иван Петров — заказ № 217", { exact: true }),
    ).toBeVisible();
    await expect(
      card.getByText("06.11.2026, 01:30 МСК", { exact: true }),
    ).toBeVisible();
    await expect(
      card.getByRole("link", { name: "Открыть акт" }),
    ).toHaveAttribute("href", `/api/admin/destructions/${id}/documents/act`);
    await expect(
      card.getByRole("link", { name: "Скачать акт" }),
    ).toHaveAttribute(
      "href",
      `/api/admin/destructions/${id}/documents/act?download=true`,
    );
    await expect(
      card.getByRole("link", { name: "Открыть выгрузку" }),
    ).toHaveAttribute(
      "href",
      `/api/admin/destructions/${id}/documents/extract`,
    );
    await expect(
      card.getByRole("link", { name: "Скачать выгрузку" }),
    ).toHaveAttribute(
      "href",
      `/api/admin/destructions/${id}/documents/extract?download=true`,
    );
    expect(await page.locator('input[type="file"]').count()).toBe(0);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: info.outputPath(`destructions-${width}.png`),
      fullPage: true,
    });
    await page.getByLabel("Поиск по субъекту или ID").fill("Неизвестный");
    await page.getByLabel("Вид операции").selectOption("customer");
    await page.getByLabel("Результат").selectOption("ready");
    await page.getByRole("button", { name: "Применить фильтры" }).focus();
    await page.keyboard.press("Enter");
    await expect(
      page.getByText("Записей по выбранным условиям нет."),
    ).toBeVisible();
    expect(queries.at(-1)?.get("q")).toBe("Неизвестный");
    expect(queries.at(-1)?.get("kind")).toBe("customer");
    expect(queries.at(-1)?.get("state")).toBe("ready");
    expect(queries.at(-1)?.get("offset")).toBe("0");
    await page.screenshot({
      path: info.outputPath(`destructions-empty-${width}.png`),
      fullPage: true,
    });
    await page.getByRole("link", { name: "Сбросить фильтры" }).click();
    await expect(page.getByRole("heading", { level: 2 })).toHaveCount(8);
  });
}

test("document retry uses CSRF and never repeats destruction", async ({
  page,
}) => {
  const state = await mockApi(page);
  let generated = false;
  await page.route("**/api/admin/destructions**", async (route) => {
    const request = route.request();
    if (request.method() === "POST") {
      expect(new URL(request.url()).pathname).toBe(
        `/api/admin/destructions/${id}/documents`,
      );
      expect(request.headers()["x-csrf-token"]).toBe("test-csrf");
      expect(request.postData()).toBe(null);
      generated = true;
      return route.fulfill({ json: ready });
    }
    return route.fulfill({
      json: [
        {
          ...ready,
          state: generated ? "ready" : "documents_pending",
          act_url: generated ? ready.act_url : null,
          extract_url: generated ? ready.extract_url : null,
        },
      ],
    });
  });
  await page.goto("/admin/destructions");
  await expect(
    page.getByText("Уничтожение подтверждено; документы ещё не сформированы."),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Повторить формирование документов" })
    .click();
  await expect(page.getByRole("link", { name: "Открыть акт" })).toBeVisible();
  await expect(page.getByText("Документы сформированы.")).toBeVisible();
  expect(generated).toBe(true);
  expect(state.deleteCount).toBe(0);
});

test("uncertain results have no documents or retry and failures remain recoverable", async ({
  page,
}, info) => {
  await mockApi(page);
  await page.route("**/api/admin/destructions**", (route) =>
    route.fulfill({
      json: [
        {
          ...ready,
          state: "uncertain",
          destroyed_at: null,
          act_url: null,
          extract_url: null,
        },
        {
          ...ready,
          id: id.slice(0, -1) + "2",
          state: "error",
          destroyed_at: null,
          act_url: null,
          extract_url: null,
        },
      ],
    }),
  );
  await page.goto("/admin/destructions");
  await expect(
    page.locator(".badge").getByText("Исход не определён", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Уничтожение не подтверждено.")).toHaveCount(2);
  expect(
    await page
      .getByRole("link", { name: /Открыть акт|Открыть выгрузку/ })
      .count(),
  ).toBe(0);
  expect(
    await page.getByRole("button", { name: /Повторить формирование/ }).count(),
  ).toBe(0);
  await page.screenshot({
    path: info.outputPath("destructions-uncertain.png"),
    fullPage: true,
  });
  await page.route("**/api/admin/destructions**", (route) =>
    route.fulfill({ status: 503, json: {} }),
  );
  await page.goto("/admin/destructions");
  await expect(
    page.getByRole("heading", { name: "Не удалось открыть раздел" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Повторить загрузку" }),
  ).toBeVisible();
  await page.screenshot({
    path: info.outputPath("destructions-error.png"),
    fullPage: true,
  });
});

test("register loading and access restrictions", async ({ page }, info) => {
  const state = await mockApi(page);
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/admin/destructions**", async (route) => {
    await gate;
    await route.fulfill({ json: [] });
  });
  await page.goto("/admin/destructions", { waitUntil: "domcontentloaded" });
  await expect(
    page.getByText(/Загрузка административной панели/),
  ).toBeVisible();
  await page.screenshot({
    path: info.outputPath("destructions-loading.png"),
    fullPage: true,
  });
  release();
  await expect(
    page.getByText("Записей по выбранным условиям нет."),
  ).toBeVisible();
  state.authenticated = false;
  await page.goto("/admin/destructions");
  await expect(page).toHaveURL(/\/auth\/admin/);
  state.authenticated = true;
  state.role = "customer";
  await page.goto("/admin/destructions");
  await expect(page).toHaveURL(/\/customer\/orders/);
});
