import { test, expect } from "@playwright/test";
import { mockApi } from "./mock-api";

const event = {
  id: "f9588fa1-8fea-4872-b1ba-30a4262f155e",
  kind: "materials_deleted",
  channel: "smtp",
  reason: "delayed",
  status: "pending",
  created_at: "2026-11-06T16:54:34Z",
  available_at: "2026-11-06T16:54:34Z",
  attempts: 0,
  error_code: null,
  order_id: "5d1de808-2b39-4ad0-90c5-ac852b690988",
  customer_id: null,
};

for (const width of [1440, 390]) {
  test(`warning opens its non-consultation event and refresh clears it at ${width}px`, async ({
    page,
  }, info) => {
    await page.setViewportSize({ width, height: 900 });
    await mockApi(page);
    let active = true;
    await page.route("**/api/admin/notifications/summary", (route) =>
      route.fulfill({
        json: active ? [{ channel: "smtp", reason: "delayed", count: 1 }] : [],
      }),
    );
    await page.route("**/api/admin/notifications/problems?*", (route) =>
      route.fulfill({ json: active ? [event] : [] }),
    );
    await page.goto("/admin/customers");
    await page
      .getByRole("link", { name: "Открыть контроль отправки уведомлений" })
      .click();
    await expect(page).toHaveURL(/view=notifications/);
    await expect(
      page.getByRole("heading", { name: "Уведомление об удалении материалов" }),
    ).toBeVisible();
    await page.getByText("Подробности уведомления", { exact: true }).click();
    await expect(page.getByText(event.id, { exact: true })).toBeVisible();
    await expect(
      page.getByText("Попыток отправки не было.", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: "Открыть заказ" }),
    ).toHaveAttribute("href", `/admin/orders/${event.order_id}`);
    await expect(
      page.getByText("Консультационных заявок с незавершённой отправкой нет."),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: info.outputPath(`problems-${width}.png`),
      fullPage: true,
    });
    active = false;
    await page.getByRole("button", { name: "Обновить", exact: true }).click();
    await expect(
      page.getByText("Проблемных уведомлений нет", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("status").filter({ hasText: "Проблемные уведомления" }),
    ).toHaveCount(0);
  });
}

test("handling a consultation refreshes both lists and the warning on other pages", async ({
  page,
}) => {
  await mockApi(page);
  let active = true;
  const id = "c55eaa2e-bad0-43d1-9b04-22aa7c439eee";
  await page.route("**/api/admin/notifications/summary", (route) =>
    route.fulfill({
      json: active ? [{ channel: "smtp", reason: "permanent", count: 1 }] : [],
    }),
  );
  await page.route("**/api/admin/notifications/problems?*", (route) =>
    route.fulfill({
      json: active
        ? [
            {
              ...event,
              kind: "consultation",
              reason: "permanent",
              status: "failed",
            },
          ]
        : [],
    }),
  );
  await page.route("**/api/admin/consultations**", (route) => {
    if (route.request().method() === "POST") {
      active = false;
      return route.fulfill({ json: { message: "ok" } });
    }
    return route.fulfill({
      json: active
        ? [
            {
              id,
              created_at: new Date().toISOString(),
              contacts_expires_at: new Date(
                Date.now() + 86400000,
              ).toISOString(),
              observed_at: new Date().toISOString(),
              email: "test@example.test",
              phone: "+79991234567",
              contacts_expiring: false,
              status: "unresolved",
              can_handle: true,
              can_retry: true,
              channels: [
                {
                  channel: "smtp",
                  status: "failed",
                  reason: "permanent",
                  attention: true,
                  retry_after: null,
                },
              ],
            },
          ]
        : [],
    });
  });
  await page.goto("/admin/consultations");
  await expect(
    page.getByRole("heading", { name: "Заявка на консультацию", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("status").filter({ hasText: "Проблемные уведомления" }),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "Отметить обработанным", exact: true })
    .click();
  await page.getByRole("button", { name: "Подтвердить обработку" }).click();
  await expect(
    page.getByText("Консультационных заявок с незавершённой отправкой нет."),
  ).toBeVisible();
  await expect(
    page.getByRole("status").filter({ hasText: "Проблемные уведомления" }),
  ).toHaveCount(0);
  await expect(
    page.getByText("Проблемных уведомлений нет", { exact: true }),
  ).toBeVisible();
  await page.goto("/admin/customers");
  await expect(
    page.getByRole("heading", { name: "Контакты и заказы" }),
  ).toBeVisible();
  await expect(
    page.getByRole("status").filter({ hasText: "Проблемные уведомления" }),
  ).toHaveCount(0);
});

test("problem list failure is visible instead of an empty state", async ({
  page,
}) => {
  await mockApi(page);
  await page.route("**/api/admin/notifications/problems?*", (route) =>
    route.fulfill({ status: 503, json: {} }),
  );
  await page.goto("/admin/consultations?view=notifications");
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Повторить загрузку" }),
  ).toBeVisible();
  await expect(page.getByText("Проблемных уведомлений нет")).toHaveCount(0);
});

test("an empty later page hides the duplicate warning and offers the first page", async ({
  page,
}) => {
  await mockApi(page);
  await page.route("**/api/admin/notifications/summary", (route) =>
    route.fulfill({ json: [{ channel: "smtp", reason: "delayed", count: 1 }] }),
  );
  await page.route("**/api/admin/notifications/problems?*", (route) => {
    const offset = new URL(route.request().url()).searchParams.get("offset");
    return route.fulfill({ json: offset === "0" ? [event] : [] });
  });
  await page.goto("/admin/consultations?view=notifications&offset=25");
  await expect(
    page.getByRole("status").filter({ hasText: "Проблемные уведомления" }),
  ).toHaveCount(0);
  await expect(
    page.getByText("Проблемных уведомлений нет", { exact: true }),
  ).toHaveCount(0);
  await page
    .getByRole("link", { name: "В начало списка", exact: true })
    .click();
  await page.getByText("Подробности уведомления", { exact: true }).click();
  await expect(page.getByText(event.id, { exact: true })).toBeVisible();
});

for (const width of [1440, 390]) {
  test(`two independent blocks and consultation subsections at ${width}px`, async ({
    page,
  }, info) => {
    await page.setViewportSize({ width, height: 900 });
    await mockApi(page);
    await page.route("**/api/admin/notifications/summary", (route) =>
      route.fulfill({
        json: [{ channel: "smtp", reason: "delayed", count: 1 }],
      }),
    );
    await page.route("**/api/admin/notifications/problems?*", (route) =>
      route.fulfill({ json: [event] }),
    );
    await page.goto(
      "/admin/consultations?view=notifications#notification-problems",
    );
    await expect(page).toHaveTitle(
      "Контроль отправки уведомлений — SINEGOR LAB",
    );
    const problems = page.getByRole("region", {
      name: "Проблемные уведомления",
      exact: true,
    });
    const consultations = page.getByRole("region", {
      name: "Консультационные заявки",
      exact: true,
    });
    await expect(problems).toBeVisible();
    await expect(consultations).toBeVisible();
    await expect(problems.getByText(event.id, { exact: true })).toBeAttached();
    await expect(
      problems.getByText("Задержка отправки", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("status").filter({ hasText: "Проблемные уведомления" }),
    ).toHaveCount(0);
    await expect(consultations).toContainText(
      "Контакты доступны до семи суток",
    );
    const active = consultations.getByRole("link", {
      name: "Отправка не завершена",
      exact: true,
    });
    const handled = consultations.getByRole("link", {
      name: "Обработаны вручную",
      exact: true,
    });
    await expect(active).toHaveAttribute("aria-current", "page");
    await expect(consultations).toContainText(
      "Консультационных заявок с незавершённой отправкой нет.",
    );
    const activeBackground = await active.evaluate(
      (el) => getComputedStyle(el).backgroundColor,
    );
    expect(activeBackground).not.toBe(
      await handled.evaluate((el) => getComputedStyle(el).backgroundColor),
    );
    await handled.click();
    await expect(handled).toHaveAttribute("aria-current", "page");
    await expect(active).not.toHaveAttribute("aria-current", "page");
    await expect(consultations).toContainText(
      "Заявок, обработанных вручную, нет.",
    );
    await expect(problems.getByText(event.id, { exact: true })).toBeAttached();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: info.outputPath(`two-blocks-${width}.png`),
      fullPage: true,
    });
  });
}

test("problem categories use meaningful status badges and safe details", async ({
  page,
}) => {
  await mockApi(page);
  await page.route("**/api/admin/notifications/problems?*", (route) =>
    route.fulfill({
      json: [
        { ...event, id: "delayed", reason: "delayed", status: "pending" },
        {
          ...event,
          id: "temporary",
          kind: "consultation_telegram",
          channel: "telegram",
          reason: "temporary",
          status: "pending",
          attempts: 2,
          error_code: "telegram_failed",
        },
        {
          ...event,
          id: "permanent",
          kind: "invitation",
          reason: "permanent",
          status: "failed",
          customer_id: "customer-217",
          order_id: null,
        },
        {
          ...event,
          id: "expired",
          kind: "magic_link",
          reason: "expired",
          status: "expired",
        },
      ],
    }),
  );
  await page.goto("/admin/consultations?view=notifications");
  const problems = page.getByRole("region", {
    name: "Проблемные уведомления",
    exact: true,
  });
  for (const label of [
    "Задержка отправки",
    "Временная ошибка",
    "Ошибка отправки",
    "Повторы прекращены",
  ])
    await expect(
      problems.locator(".badge").filter({ hasText: label }),
    ).toBeVisible();
  await expect(
    problems.getByRole("link", { name: "Открыть заказчика" }),
  ).toHaveAttribute("href", "/admin/customers/customer-217");
  const temporary = problems
    .locator(".consultation-card")
    .filter({ hasText: "Временная ошибка" });
  await expect(temporary).toContainText("Попыток отправки: 2.");
  await expect(temporary).toContainText("Следующая попытка");
  await expect(
    temporary.getByRole("link", { name: "Открыть консультационные заявки" }),
  ).toHaveAttribute("href", "/admin/consultations#consultation-requests");
});

test("pagination of the problem list does not paginate consultations", async ({
  page,
}) => {
  await mockApi(page);
  const requests: string[] = [];
  await page.route("**/api/admin/consultations?*", (route) => {
    requests.push(
      new URL(route.request().url()).searchParams.get("offset") ?? "",
    );
    return route.fulfill({ json: [] });
  });
  await page.route("**/api/admin/notifications/problems?*", (route) => {
    const start = new URL(route.request().url()).searchParams.get("offset");
    return route.fulfill({
      json:
        start === "0"
          ? Array.from({ length: 25 }, (_, i) => ({
              ...event,
              id: `problem-${i}`,
            }))
          : [],
    });
  });
  await page.goto("/admin/consultations?view=handled");
  const problems = page.getByRole("region", {
    name: "Проблемные уведомления",
    exact: true,
  });
  await problems.getByRole("link", { name: "Далее", exact: true }).click();
  await expect(problems).toContainText(
    "На этой странице проблемных уведомлений нет.",
  );
  await expect(
    page.getByRole("region", { name: "Консультационные заявки", exact: true }),
  ).toContainText("Заявок, обработанных вручную, нет.");
  expect(requests.length).toBeGreaterThan(0);
  expect(requests.every((value) => value === "0")).toBe(true);
});

test("problem navigation preserves handled consultation page", async ({
  page,
}) => {
  await mockApi(page);
  await page.goto(
    "/admin/consultations?view=handled&consultations_offset=25&problems_offset=25",
  );
  const problems = page.getByRole("region", {
    name: "Проблемные уведомления",
    exact: true,
  });
  await problems
    .getByRole("link", { name: "В начало списка", exact: true })
    .click();
  await expect(page).toHaveURL(/view=handled/);
  await expect(page).toHaveURL(/consultations_offset=25/);
  await expect(problems).toContainText("Проблемных уведомлений нет");
  const nav = page.getByRole("navigation", {
    name: "Разделы контроля отправки",
  });
  await nav
    .getByRole("link", { name: "Проблемные уведомления", exact: true })
    .click();
  await expect(page).toHaveURL(/view=handled/);
  await expect(page).toHaveURL(/consultations_offset=25/);
  await expect(
    nav.getByRole("link", { name: "Проблемные уведомления", exact: true }),
  ).toHaveAttribute("aria-current", "location");
  await expect(
    page
      .getByRole("navigation", { name: "Состояние заявок" })
      .getByRole("link", { name: "Обработаны вручную", exact: true }),
  ).toHaveAttribute("aria-current", "page");
});

test("automatic expiry does not promise a next attempt but a manual retry does", async ({
  page,
}) => {
  await mockApi(page);
  await page.route("**/api/admin/notifications/problems?*", (route) =>
    route.fulfill({
      json: [
        {
          ...event,
          id: "expired-pending",
          status: "pending",
          reason: "expired",
        },
        {
          ...event,
          id: "manual-pending",
          status: "pending",
          reason: "expired",
          error_code: "manual_retry",
        },
        { ...event, id: "processing", status: "processing", reason: "delayed" },
      ],
    }),
  );
  await page.goto("/admin/consultations?view=notifications");
  const cards = page
    .getByRole("region", { name: "Проблемные уведомления", exact: true })
    .locator(".consultation-card");
  const expired = cards.filter({ hasText: "expired-pending" });
  const manual = cards.filter({ hasText: "manual-pending" });
  const processing = cards.filter({ hasText: "Событие: processing" });
  await expect(expired.locator(".badge")).toHaveText("Повторы прекращены");
  await expect(expired).not.toContainText("Следующая попытка");
  await expect(manual.locator(".badge")).toHaveText("Ожидает отправки");
  await expect(manual).toContainText("Следующая попытка");
  await expect(processing.locator(".badge")).toHaveText("Отправляется");
});
