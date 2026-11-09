import { test, expect } from "@playwright/test";
import { mockApi } from "./mock-api";

for (const width of [1440, 390]) {
  test(`security events are read only and filterable with keyboard ${width}`, async ({
    page,
  }, info) => {
    await page.setViewportSize({ width, height: 900 });
    await mockApi(page);
    const queries: URLSearchParams[] = [];
    const mutations: string[] = [];
    await page.route("**/api/admin/security-events**", async (route) => {
      const request = route.request();
      if (request.method() !== "GET") mutations.push(request.method());
      const query = new URL(request.url()).searchParams;
      queries.push(query);
      return route.fulfill({
        json: query.get("date_from")
          ? []
          : [
              {
                id: "10000000-0000-4000-8000-000000000001",
                recorded_at: "2026-11-05T10:00:00Z",
                event_type: "authentication",
                result: "success",
                user_id: "20000000-0000-4000-8000-000000000002",
                user_role: "admin",
                subject_user_id: null,
                request_id: "0123456789abcdef0123456789abcdef",
                reason_code: "admin_login",
              },
            ],
      });
    });
    await page.goto("/admin/security-events");
    await expect(
      page.getByRole("heading", { name: "События безопасности", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("Вход администратора", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("0123456789abcdef0123456789abcdef", { exact: true }),
    ).toBeVisible();
    expect(
      await page.getByRole("button", { name: /Удалить|Редактировать/ }).count(),
    ).toBe(0);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    const screenshot = info.outputPath(`security-events-${width}.png`);
    await page.screenshot({ path: screenshot, fullPage: true });
    await page.getByLabel("Дата с (UTC)").fill("2026-11-01");
    await page.getByLabel("Дата по (UTC)").fill("2026-11-05");
    await page.getByLabel("Тип события").selectOption("authentication");
    await page.getByRole("button", { name: "Применить фильтры" }).focus();
    await page.keyboard.press("Enter");
    await expect(
      page.getByText("Событий по выбранным условиям нет."),
    ).toBeVisible();
    expect(queries.at(-1)?.get("date_from")).toBe("2026-11-01");
    expect(queries.at(-1)?.get("date_to")).toBe("2026-11-05");
    expect(queries.at(-1)?.get("event_type")).toBe("authentication");
    await page.getByRole("link", { name: "Сбросить фильтры" }).focus();
    await page.keyboard.press("Enter");
    await expect(
      page.getByText("Вход администратора", { exact: true }),
    ).toBeVisible();
    expect(mutations).toEqual([]);
  });
}

test("security journal handles request failure and customer redirect", async ({
  page,
}) => {
  const state = await mockApi(page);
  await page.route("**/api/admin/security-events**", (route) =>
    route.fulfill({
      status: 503,
      json: { error: { message: "Unavailable" }, request_id: "test-request" },
    }),
  );
  await page.goto("/admin/security-events");
  await expect(page.getByRole("heading", { name: /Не удалось/ })).toBeVisible();
  state.role = "customer";
  await page.goto("/admin/security-events");
  await expect(page).toHaveURL(/\/customer\/orders/);
});

for (const timezoneId of ["UTC", "America/Los_Angeles", "Asia/Tokyo"]) {
  test.describe(`security journal in ${timezoneId}`, () => {
    test.use({ timezoneId });

    for (const width of [1440, 390]) {
      test(`shows Moscow event times without changing instants or order ${width}`, async ({
        page,
      }, info) => {
        await page.setViewportSize({ width, height: 900 });
        await mockApi(page);
        await page.route("**/api/admin/security-events**", (route) =>
          route.fulfill({
            json: [
              {
                id: "10000000-0000-4000-8000-000000000001",
                recorded_at: "2026-11-05T22:30:15.123Z",
                event_type: "authentication",
                result: "success",
                user_id: "20000000-0000-4000-8000-000000000002",
                user_role: "admin",
                subject_user_id: null,
                request_id: "0123456789abcdef0123456789abcdef",
                reason_code: "admin_login",
              },
              {
                id: "10000000-0000-4000-8000-000000000003",
                recorded_at: "2026-11-05T12:00:00+02:00",
                event_type: "authentication",
                result: "success",
                user_id: "20000000-0000-4000-8000-000000000002",
                user_role: "admin",
                subject_user_id: null,
                request_id: "0123456789abcdef0123456789abcdef",
                reason_code: "admin_login",
              },
            ],
          }),
        );
        await page.goto("/admin/security-events");
        const times = page.locator("time");
        await expect(times).toHaveText([
          "06.11.2026, 01:30:15 МСК",
          "05.11.2026, 13:00:00 МСК",
        ]);
        await expect(times.nth(0)).toHaveAttribute(
          "datetime",
          "2026-11-05T22:30:15.123Z",
        );
        await expect(times.nth(1)).toHaveAttribute(
          "datetime",
          "2026-11-05T12:00:00+02:00",
        );
        await expect(page.getByText(/московское время/)).toBeVisible();
        await expect(page.getByLabel("Дата с (UTC)")).toBeVisible();
        await expect(page.getByLabel("Дата по (UTC)")).toBeVisible();
        expect(
          await page.evaluate(
            () => document.documentElement.scrollWidth <= innerWidth,
          ),
        ).toBe(true);
        await page.screenshot({
          path: info.outputPath(`moscow-${width}.png`),
          fullPage: true,
        });
      });
    }
  });
}
