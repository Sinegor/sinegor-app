import { test, expect, type Page } from "@playwright/test";
import { mockApi } from "./mock-api";
import type { Models } from "../../app/lib/admin/api";

const id = "c55eaa2e-bad0-43d1-9b04-22aa7c439eee";
function requestRow(): Models["ConsultationRead"] {
  return {
    id,
    observed_at: new Date().toISOString(),
    created_at: new Date(Date.now() - 6 * 86400000).toISOString(),
    contacts_expires_at: new Date(Date.now() + 86400000).toISOString(),
    email: "panel@example.test",
    phone: "+79991234567",
    contacts_expiring: true,
    status: "unresolved",
    channels: [
      {
        channel: "smtp",
        status: "expired",
        reason: "expired",
        attention: true,
        retry_after: null,
      },
      {
        channel: "telegram",
        status: "sent",
        reason: null,
        attention: false,
        retry_after: null,
      },
    ],
    can_handle: true,
    can_retry: true,
  };
}
async function setup(page: Page) {
  const auth = await mockApi(page);
  const state = {
    rows: [requestRow()],
    calls: [] as { path: string; body: unknown; csrf: string | undefined }[],
    fail: false,
  };
  await page.route("**/api/admin/consultations**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() === "GET") {
      const handled = url.searchParams.get("view") === "handled";
      return route.fulfill({
        json: state.rows.filter(
          (row) => (row.status === "handled") === handled,
        ),
      });
    }
    state.calls.push({
      path: url.pathname,
      body: request.postDataJSON(),
      csrf: request.headers()["x-csrf-token"],
    });
    if (state.fail)
      return route.fulfill({
        status: 409,
        json: { error: { message: "private provider text" } },
      });
    if (url.pathname.endsWith("/handle")) {
      state.rows = state.rows.map((row) => ({
        ...row,
        status: "handled",
        email: null,
        phone: null,
        can_handle: false,
        can_retry: false,
      }));
    } else state.rows = [];
    return route.fulfill({
      status: url.pathname.endsWith("/retry") ? 202 : 200,
      json: { message: "ok" },
    });
  });
  return { state, auth };
}

for (const width of [1440, 390]) {
  test(`consultation panel supports keyboard confirmation and responsive layout ${width}`, async ({
    page,
  }, info) => {
    await page.setViewportSize({ width, height: 900 });
    const { state } = await setup(page);
    await page.goto("/admin/consultations");
    await expect(
      page.getByRole("heading", { name: "Проблемы доставки", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("panel@example.test", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText(/Контакты будут удалены менее чем через 24 часа/),
    ).toBeVisible();
    await expect(
      page.getByText("Telegram: отправлено", { exact: true }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: info.outputPath(`panel-${width}.png`),
      fullPage: true,
    });
    const retry = page.getByRole("button", {
      name: "Повторить отправку: Email",
    });
    await retry.focus();
    await page.keyboard.press("Enter");
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("heading")).toBeFocused();
    expect(state.calls).toHaveLength(0);
    await page.keyboard.press("Escape");
    await expect(dialog).not.toBeVisible();
    await expect(retry).toBeFocused();
    await page.keyboard.press("Enter");
    await dialog.getByRole("button", { name: "Подтвердить отправку" }).focus();
    await page.keyboard.press("Enter");
    await expect(
      page.getByText("Недоставленных консультационных заявок нет."),
    ).toBeVisible();
    expect(state.calls).toEqual([
      {
        path: `/api/admin/consultations/${id}/retry`,
        body: { channel: "smtp", confirmed: true },
        csrf: "test-csrf",
      },
    ]);
  });
}

test("manual handling requires confirmation and exposes an unambiguous handled state", async ({
  page,
}) => {
  const { state } = await setup(page);
  await page.goto("/admin/consultations");
  await page
    .getByRole("button", { name: "Отметить обработанным", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("Контакты будут очищены");
  expect(state.calls).toHaveLength(0);
  await dialog.getByRole("button", { name: "Подтвердить обработку" }).click();
  await expect(
    page.getByText("Недоставленных консультационных заявок нет."),
  ).toBeVisible();
  await page.getByRole("link", { name: "Обработанные", exact: true }).click();
  await expect(
    page.getByText("Обработано вручную", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("panel@example.test", { exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: /Повторить отправку/ }),
  ).toHaveCount(0);
  expect(state.calls[0].body).toEqual({ confirmed: true });
});

test("expired contacts disappear on an already open page even when refresh hangs", async ({
  page,
}) => {
  await page.clock.install();
  const { state } = await setup(page);
  state.rows[0].contacts_expires_at = new Date(Date.now() + 2000).toISOString();
  await page.goto("/admin/consultations");
  await expect(
    page.getByText("panel@example.test", { exact: true }),
  ).toBeVisible();
  await page.route("**/api/admin/consultations**", async () => {
    await new Promise(() => {});
  });
  await page.clock.fastForward(3000);
  await expect(
    page.getByText("panel@example.test", { exact: true }),
  ).toHaveCount(0);
  await expect(page.getByText("+79991234567", { exact: true })).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: /Повторить отправку/ }),
  ).toHaveCount(0);
});

test("mutation failure stays safe and allows review before retry", async ({
  page,
}) => {
  const { state } = await setup(page);
  state.fail = true;
  await page.goto("/admin/consultations");
  await page.getByRole("button", { name: "Повторить отправку: Email" }).click();
  await page.getByRole("button", { name: "Подтвердить отправку" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Данные или условия операции изменились",
  );
  await expect(page.getByText("private provider text")).toHaveCount(0);
  await expect(
    page.getByText("panel@example.test", { exact: true }),
  ).toBeVisible();
});

test("only administrators can open the panel", async ({ page }) => {
  const { auth } = await setup(page);
  auth.role = "customer";
  await page.goto("/admin/consultations");
  await expect(page).toHaveURL("/customer/orders");
  await expect(
    page.getByText("panel@example.test", { exact: true }),
  ).toHaveCount(0);
});

test("panel reports unavailable data and provides a retry", async ({
  page,
}) => {
  await setup(page);
  await page.route("**/api/admin/consultations**", (route) =>
    route.fulfill({ status: 503, json: {} }),
  );
  await page.goto("/admin/consultations");
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Повторить загрузку" }),
  ).toBeVisible();
});

test("contact expiry follows the server window with a skewed browser clock", async ({
  page,
}) => {
  await page.clock.install({ time: new Date("2020-01-01T00:00:00Z") });
  const { state } = await setup(page);
  state.rows[0].contacts_expires_at = new Date(Date.now() + 2000).toISOString();
  await page.goto("/admin/consultations");
  await expect(
    page.getByText("panel@example.test", { exact: true }),
  ).toBeVisible();
  await page.clock.fastForward(3000);
  await expect(
    page.getByText("panel@example.test", { exact: true }),
  ).toHaveCount(0);
});

test("a fast or changed browser wall clock cannot shorten the server contact window", async ({
  page,
}) => {
  await page.clock.install({ time: new Date("2030-01-01T00:00:00Z") });
  const { state } = await setup(page);
  state.rows[0].contacts_expires_at = new Date(Date.now() + 2000).toISOString();
  await page.goto("/admin/consultations");
  await expect(
    page.getByText("panel@example.test", { exact: true }),
  ).toBeVisible();
  await page.clock.setSystemTime(new Date("2040-01-01T00:00:00Z"));
  await expect(
    page.getByText("panel@example.test", { exact: true }),
  ).toBeVisible();
  await page.clock.fastForward(3000);
  await expect(
    page.getByText("panel@example.test", { exact: true }),
  ).toHaveCount(0);
});

test("provider retry interval disables manual delivery while showing the allowed date", async ({
  page,
}) => {
  const { state } = await setup(page);
  state.rows[0].channels = [
    {
      channel: "smtp",
      status: "sent",
      reason: null,
      attention: false,
      retry_after: null,
    },
    {
      channel: "telegram",
      status: "pending",
      reason: "temporary",
      attention: true,
      retry_after: new Date(Date.now() + 3600000).toISOString(),
    },
  ];
  await page.goto("/admin/consultations");
  await expect(page.getByText(/Повтор возможен после/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Повторить отправку: Telegram" }),
  ).toBeDisabled();
  expect(state.calls).toHaveLength(0);
});
