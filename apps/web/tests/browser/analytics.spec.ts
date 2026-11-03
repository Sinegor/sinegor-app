import { test, expect, type Page } from "@playwright/test";
import { createServer } from "node:http";
import { spawn, type ChildProcess } from "node:child_process";
import { once } from "node:events";
import type { AddressInfo } from "node:net";

const scriptUrl = "https://mc.yandex.ru/metrika/tag.js";
const mockScript = `(() => {
  const queue = window.ym?.a || [];
  window.__metrikaCalls ||= [];
  window.ym = (...args) => window.__metrikaCalls.push(args);
  for (const args of queue) window.ym(...args);
})();`;
type Call = [number, string, ...unknown[]];
const calls = (page: Page) =>
  page.evaluate(
    () =>
      (window as unknown as { __metrikaCalls?: Call[] }).__metrikaCalls || [],
  );
const hits = async (page: Page) =>
  (await calls(page)).filter((call) => call[1] === "hit");
const goals = async (page: Page, name: string) =>
  (await calls(page)).filter(
    (call) => call[1] === "reachGoal" && call[2] === name,
  );
const allowAnalytics = (page: Page) =>
  page
    .getByRole("region", { name: "Настройки аналитики" })
    .getByRole("button", { name: "Разрешить", exact: true })
    .click();
let origin: string;
let server: ChildProcess;

test.beforeAll(async () => {
  const reservation = createServer().listen(0, "127.0.0.1");
  await once(reservation, "listening");
  const port = (reservation.address() as AddressInfo).port;
  await new Promise<void>((resolve) => reservation.close(() => resolve()));
  origin = `http://127.0.0.1:${port}`;
  server = spawn(
    process.execPath,
    ["node_modules/@react-router/serve/bin.js", "./build/server/index.js"],
    {
      env: {
        ...process.env,
        NODE_ENV: "production",
        HOST: "127.0.0.1",
        PORT: String(port),
        CMS_ORIGIN: "",
        PUBLIC_ORIGIN: origin,
        YANDEX_METRIKA_ENABLED: "true",
        YANDEX_METRIKA_ID: "12345678",
      },
      stdio: "ignore",
    },
  );
  await expect
    .poll(async () => {
      try {
        return (await fetch(origin)).status;
      } catch {
        return 0;
      }
    })
    .toBe(200);
});
test.afterAll(async () => {
  if (!server || server.exitCode !== null) return;
  const exited = once(server, "exit");
  server.kill("SIGTERM");
  await exited;
});

test.beforeEach(async ({ context }) => {
  await context.route("**/*", (route) =>
    ["localhost", "127.0.0.1"].includes(new URL(route.request().url()).hostname)
      ? route.continue()
      : route.abort(),
  );
  await context.route(scriptUrl, (route) =>
    route.fulfill({ contentType: "application/javascript", body: mockScript }),
  );
  await context.route("**/api/auth/session", (route) =>
    route.fulfill({ status: 401, json: {} }),
  );
});

test("SSR stays browser-free; initial and client views are counted once and video requires playback", async ({
  page,
  request,
}) => {
  const html = await (await request.get(origin)).text();
  expect(html).not.toContain(`<script src="${scriptUrl}"`);
  await page.goto(origin + "/?email=private@example.test#secret");
  await allowAnalytics(page);
  await expect.poll(() => hits(page)).toHaveLength(1);
  expect((await hits(page))[0][2]).toBe(origin + "/");
  expect(await goals(page, "video_presentation_view")).toHaveLength(0);
  const video = page.locator("video");
  await video.evaluate(async (element: HTMLVideoElement) => {
    await element.play();
  });
  await expect
    .poll(() => goals(page, "video_presentation_view"))
    .toHaveLength(1);
  await video.evaluate((element: HTMLVideoElement) => element.pause());
  await video.evaluate(async (element: HTMLVideoElement) => {
    await element.play();
  });
  await video.evaluate((element: HTMLVideoElement) => element.pause());
  expect(await goals(page, "video_presentation_view")).toHaveLength(1);
  await page
    .getByRole("navigation", { name: "Основная навигация" })
    .getByRole("link", { name: "ИИ-анализ", exact: true })
    .click();
  await expect.poll(() => hits(page)).toHaveLength(2);
  expect(await goals(page, "service_view")).toHaveLength(1);
  await page.locator('a[href="/contacts#consultation"]').click();
  await expect.poll(() => goals(page, "consultation_open")).toHaveLength(1);
  expect(await hits(page)).toHaveLength(3);
  await page.locator("header .brand").click();
  await expect.poll(() => hits(page)).toHaveLength(4);
  expect(JSON.stringify(await calls(page))).not.toMatch(
    /private@example|email=|#secret/,
  );
});

test("consultation goal requires API success and contains no form values", async ({
  page,
}) => {
  let status = 500;
  await page.route("**/api/auth/csrf", (route) =>
    route.fulfill({ json: { csrf_token: "test" } }),
  );
  await page.route("**/api/consultations", (route) =>
    route.fulfill({ status, json: {} }),
  );
  await page.goto(origin + "/contacts#consultation");
  await allowAnalytics(page);
  await expect.poll(() => goals(page, "consultation_open")).toHaveLength(1);
  await page
    .getByRole("button", { name: "Запросить консультацию", exact: true })
    .click();
  expect(await goals(page, "consultation_submit")).toHaveLength(0);
  await page.getByLabel("Ваш email").fill("private@example.test");
  await page.getByLabel("Ваш телефон").fill("+79991234567");
  await page
    .getByRole("button", { name: "Запросить консультацию", exact: true })
    .click();
  await expect(page.getByRole("alert")).toBeVisible();
  expect(await goals(page, "consultation_submit")).toHaveLength(0);
  status = 202;
  await page
    .getByRole("button", { name: "Запросить консультацию", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("Заявка принята");
  await expect.poll(() => goals(page, "consultation_submit")).toHaveLength(1);
  expect(JSON.stringify(await calls(page))).not.toMatch(
    /private@example|79991234567|csrf|#consultation/,
  );
});

test("private visits never load a counter; leaving public pages destructs it and returning initializes once", async ({
  page,
}) => {
  for (const path of [
    "/auth/login?email=private@example.test",
    "/auth/magic-link#token-secret",
    "/customer/orders",
    "/admin/orders",
  ]) {
    await page.goto(origin + path);
    await expect(page.locator("h1")).toBeVisible();
    expect(await calls(page)).toHaveLength(0);
    await expect(page.locator(`script[src="${scriptUrl}"]`)).toHaveCount(0);
  }
  await page.goto(origin);
  await allowAnalytics(page);
  await expect.poll(() => hits(page)).toHaveLength(1);
  await page.getByRole("link", { name: "Вход заказчика", exact: true }).click();
  await expect(page).toHaveURL(origin + "/auth/login");
  await expect
    .poll(async () =>
      (await calls(page)).filter((call) => call[1] === "destruct"),
    )
    .toHaveLength(1);
  expect(await hits(page)).toHaveLength(1);
  await page.locator("header .brand").click();
  await expect.poll(() => hits(page)).toHaveLength(2);
  expect((await calls(page)).filter((call) => call[1] === "init")).toHaveLength(
    2,
  );
  expect(JSON.stringify(await calls(page))).not.toMatch(
    /token-secret|private@example|customer|admin|\/auth\//,
  );
});

test("a late script cannot initialize tracking after navigation to login", async ({
  page,
}) => {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(scriptUrl, async (route) => {
    await gate;
    await route
      .fulfill({ contentType: "application/javascript", body: mockScript })
      .catch(() => {});
  });
  await page.goto(origin, { waitUntil: "domcontentloaded" });
  await allowAnalytics(page);
  await expect(page.locator(`script[src="${scriptUrl}"]`)).toHaveCount(1);
  await page.getByRole("link", { name: "Вход заказчика", exact: true }).click();
  await expect(page).toHaveURL(origin + "/auth/login");
  release();
  await page.waitForLoadState("networkidle");
  expect(await calls(page)).toHaveLength(0);
});

test("blocked external analytics cannot prevent consultation or navigation", async ({
  page,
}) => {
  await page.route(scriptUrl, (route) => route.abort());
  await page.route("**/api/auth/csrf", (route) =>
    route.fulfill({ json: { csrf_token: "test" } }),
  );
  await page.route("**/api/consultations", (route) =>
    route.fulfill({ status: 202, json: {} }),
  );
  await page.goto(origin + "/contacts");
  await allowAnalytics(page);
  await page.getByLabel("Ваш email").fill("private@example.test");
  await page.getByLabel("Ваш телефон").fill("+79991234567");
  await page
    .getByRole("button", { name: "Запросить консультацию", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("Заявка принята");
  await page.getByRole("link", { name: "Документы", exact: true }).click();
  await expect(page).toHaveURL(origin + "/documents");
  expect(await calls(page)).toHaveLength(0);
});

test("the default environment never loads analytics", async ({
  page,
  baseURL,
}) => {
  await page.goto(baseURL!);
  await page.getByRole("link", { name: "Документы", exact: true }).click();
  await expect(page.locator("h1")).toHaveText("Документы");
  await expect(page.locator(`script[src="${scriptUrl}"]`)).toHaveCount(0);
  expect(await calls(page)).toHaveLength(0);
});

test("a first visit never loads tracking before the visitor chooses", async ({
  page,
}) => {
  await page.goto(origin, { waitUntil: "networkidle" });
  await expect(
    page.getByRole("region", { name: "Настройки аналитики" }),
  ).toBeVisible();
  await expect(page.locator(`script[src="${scriptUrl}"]`)).toHaveCount(0);
  expect(await calls(page)).toHaveLength(0);
  await page
    .getByRole("region", { name: "Настройки аналитики" })
    .getByRole("button", { name: "Отклонить", exact: true })
    .click();
  await page
    .getByRole("navigation", { name: "Основная навигация" })
    .getByRole("link", { name: "Документы", exact: true })
    .click();
  await expect(page.locator("h1")).toHaveText("Документы");
  await page.reload({ waitUntil: "networkidle" });
  await expect(
    page.getByRole("region", { name: "Настройки аналитики" }),
  ).toHaveCount(0);
  expect(await calls(page)).toHaveLength(0);
  await page
    .getByRole("button", { name: "Настройки аналитики", exact: true })
    .click();
  await page
    .getByRole("dialog", { name: "Настройки аналитики" })
    .getByRole("button", { name: "Разрешить", exact: true })
    .click();
  await expect.poll(() => hits(page)).toHaveLength(1);
  await page.reload({ waitUntil: "networkidle" });
  await expect.poll(() => hits(page)).toHaveLength(1);
  await expect(
    page.getByRole("region", { name: "Настройки аналитики" }),
  ).toHaveCount(0);
});

test("withdrawing consent stops the loaded counter and future events", async ({
  page,
}) => {
  await page.goto(origin);
  await allowAnalytics(page);
  await expect.poll(() => hits(page)).toHaveLength(1);
  await page
    .getByRole("button", { name: "Настройки аналитики", exact: true })
    .click();
  await page
    .getByRole("dialog", { name: "Настройки аналитики" })
    .getByRole("button", { name: "Отклонить", exact: true })
    .click();
  await expect
    .poll(async () =>
      (await calls(page)).filter((call) => call[1] === "destruct"),
    )
    .toHaveLength(1);
  await expect(page.locator(`script[src="${scriptUrl}"]`)).toHaveCount(0);
  await page.locator("video").evaluate(async (video: HTMLVideoElement) => {
    await video.play();
    video.pause();
  });
  expect(await goals(page, "video_presentation_view")).toHaveLength(0);
  await page
    .getByRole("navigation", { name: "Основная навигация" })
    .getByRole("link", { name: "Документы", exact: true })
    .click();
  expect(await hits(page)).toHaveLength(1);
  await page.reload({ waitUntil: "networkidle" });
  expect(await calls(page)).toHaveLength(0);
});

test("withdrawing consent before tag.js finishes cannot initialize a late counter", async ({
  page,
}) => {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(scriptUrl, async (route) => {
    await gate;
    await route
      .fulfill({ contentType: "application/javascript", body: mockScript })
      .catch(() => {});
  });
  await page.goto(origin, { waitUntil: "domcontentloaded" });
  await allowAnalytics(page);
  await expect(page.locator(`script[src="${scriptUrl}"]`)).toHaveCount(1);
  await page
    .getByRole("button", { name: "Настройки аналитики", exact: true })
    .click();
  await page
    .getByRole("dialog", { name: "Настройки аналитики" })
    .getByRole("button", { name: "Отклонить", exact: true })
    .click();
  release();
  await page.waitForLoadState("networkidle");
  expect(await calls(page)).toHaveLength(0);
});

test("revocation in another tab stops tracking and the expiry prompts for a new decision", async ({
  page,
  context,
}) => {
  await page.goto(origin);
  await allowAnalytics(page);
  await expect.poll(() => hits(page)).toHaveLength(1);
  const other = await context.newPage();
  await other.goto(origin);
  await other
    .getByRole("button", { name: "Настройки аналитики", exact: true })
    .click();
  await other
    .getByRole("dialog", { name: "Настройки аналитики" })
    .getByRole("button", { name: "Отклонить", exact: true })
    .click();
  await expect
    .poll(async () =>
      (await calls(page)).filter((call) => call[1] === "destruct"),
    )
    .toHaveLength(1);
  await page.evaluate(() =>
    localStorage.setItem(
      "sinegor.analytics-consent.v1",
      JSON.stringify({ decision: "accepted", expiresAt: 1 }),
    ),
  );
  await page.reload({ waitUntil: "networkidle" });
  await expect(
    page.getByRole("region", { name: "Настройки аналитики" }),
  ).toBeVisible();
  expect(await calls(page)).toHaveLength(0);
  await other.close();
});

test("unavailable storage does not start tracking or prevent an explicit decision", async ({
  page,
}) => {
  await page.addInitScript(() =>
    Object.defineProperty(window, "localStorage", {
      get() {
        throw new Error("blocked");
      },
    }),
  );
  await page.goto(origin, { waitUntil: "networkidle" });
  expect(await calls(page)).toHaveLength(0);
  await allowAnalytics(page);
  await expect.poll(() => hits(page)).toHaveLength(1);
  await page.reload({ waitUntil: "networkidle" });
  expect(await calls(page)).toHaveLength(0);
  await expect(
    page.getByRole("region", { name: "Настройки аналитики" }),
  ).toBeVisible();
});

test("expiry stops an active counter without waiting for a reload", async ({
  page,
}) => {
  await page.clock.install();
  await page.addInitScript(() =>
    localStorage.setItem(
      "sinegor.analytics-consent.v1",
      JSON.stringify({ decision: "accepted", expiresAt: Date.now() + 60_000 }),
    ),
  );
  await page.goto(origin);
  await expect.poll(() => hits(page)).toHaveLength(1);
  await page.clock.fastForward(61_000);
  await expect(
    page.getByRole("region", { name: "Настройки аналитики" }),
  ).toBeVisible();
  await expect
    .poll(async () =>
      (await calls(page)).filter((call) => call[1] === "destruct"),
    )
    .toHaveLength(1);
  await expect(page.locator(`script[src="${scriptUrl}"]`)).toHaveCount(0);
});

test("stored permission never activates analytics on a private route", async ({
  page,
}) => {
  await page.addInitScript(() =>
    localStorage.setItem(
      "sinegor.analytics-consent.v1",
      JSON.stringify({
        decision: "accepted",
        expiresAt: Date.now() + 86400000,
      }),
    ),
  );
  for (const path of [
    "/auth/login",
    "/auth/admin",
    "/auth/magic-link",
    "/customer/orders",
    "/admin/orders",
  ]) {
    await page.goto(origin + path, { waitUntil: "networkidle" });
    await expect(page.locator(`script[src="${scriptUrl}"]`)).toHaveCount(0);
    await expect(
      page.getByRole("region", { name: "Настройки аналитики" }),
    ).toHaveCount(0);
    expect(await calls(page)).toHaveLength(0);
  }
});

test("granting permission again on the same visit never recounts its page or video", async ({
  page,
}) => {
  await page.goto(origin);
  await allowAnalytics(page);
  await expect.poll(() => hits(page)).toHaveLength(1);
  await page.locator("video").evaluate(async (video: HTMLVideoElement) => {
    await video.play();
    video.pause();
  });
  await expect
    .poll(() => goals(page, "video_presentation_view"))
    .toHaveLength(1);
  for (const name of ["Отклонить", "Разрешить"]) {
    await page
      .getByRole("button", { name: "Настройки аналитики", exact: true })
      .click();
    await page
      .getByRole("dialog", { name: "Настройки аналитики" })
      .getByRole("button", { name, exact: true })
      .click();
  }
  await expect
    .poll(async () => (await calls(page)).filter((call) => call[1] === "init"))
    .toHaveLength(2);
  expect(await hits(page)).toHaveLength(1);
  await page.locator("video").evaluate(async (video: HTMLVideoElement) => {
    await video.play();
    video.pause();
  });
  expect(await goals(page, "video_presentation_view")).toHaveLength(1);
});

test("playback before permission does not consume the first permitted video view", async ({
  page,
}) => {
  await page.goto(origin);
  const video = page.locator("video");
  await video.evaluate(async (element: HTMLVideoElement) => {
    await element.play();
    element.pause();
  });
  expect(await goals(page, "video_presentation_view")).toHaveLength(0);
  await expect(page.locator(`script[src="${scriptUrl}"]`)).toHaveCount(0);
  await allowAnalytics(page);
  await expect.poll(() => hits(page)).toHaveLength(1);
  expect(await goals(page, "video_presentation_view")).toHaveLength(0);
  await video.evaluate(async (element: HTMLVideoElement) => {
    await element.play();
    element.pause();
  });
  await expect
    .poll(() => goals(page, "video_presentation_view"))
    .toHaveLength(1);
});

test("a new home visit counts playback even when navigation retains the real player", async ({
  page,
}) => {
  await page.goto(origin);
  await allowAnalytics(page);
  await expect.poll(() => hits(page)).toHaveLength(1);
  const video = await page.locator("video").elementHandle();
  await video!.evaluate(async (element: HTMLVideoElement) => {
    await element.play();
    element.pause();
  });
  await expect
    .poll(() => goals(page, "video_presentation_view"))
    .toHaveLength(1);
  await page.locator("header .brand").click();
  expect(await video!.evaluate((element) => element.isConnected)).toBe(true);
  await video!.evaluate(async (element: HTMLVideoElement) => {
    await element.play();
    element.pause();
  });
  await expect
    .poll(() => goals(page, "video_presentation_view"))
    .toHaveLength(2);
});

test("consent controls fit desktop and mobile and settings restore keyboard focus", async ({
  page,
}, testInfo) => {
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(origin);
    const prompt = page.getByRole("region", { name: "Настройки аналитики" });
    await expect(prompt).toBeVisible();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(width);
    await prompt.screenshot({
      path: testInfo.outputPath(`consent-${width}.png`),
    });
    const settings = page.getByRole("button", {
      name: "Настройки аналитики",
      exact: true,
    });
    await settings.focus();
    await page.keyboard.press("Enter");
    const dialog = page.getByRole("dialog", { name: "Настройки аналитики" });
    await expect(dialog.getByRole("heading")).toBeFocused();
    const box = await dialog.boundingBox();
    expect(box!.width).toBeLessThanOrEqual(width);
    await dialog.screenshot({
      path: testInfo.outputPath(`settings-${width}.png`),
    });
    await page.keyboard.press("Escape");
    await expect(dialog).not.toBeVisible();
    await expect(settings).toBeFocused();
  }
});
