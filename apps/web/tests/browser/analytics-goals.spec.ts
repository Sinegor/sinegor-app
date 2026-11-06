import { test, expect } from "@playwright/test";
import { build } from "vite";
import { createServer, type Server } from "node:http";
import { once } from "node:events";
import type { AddressInfo } from "node:net";

let server: Server;
let origin: string;
test.beforeAll(async () => {
  const result = await build({
    configFile: false,
    logLevel: "silent",
    define: { "process.env.NODE_ENV": JSON.stringify("production") },
    build: {
      write: false,
      lib: {
        entry: "tests/browser/fixtures/analytics-goal-harness.tsx",
        formats: ["iife"],
        name: "AnalyticsHarness",
      },
    },
  });
  const bundle = (Array.isArray(result) ? result[0] : result) as {
    output: { type: string; code?: string }[];
  };
  const script = bundle.output.find((item) => item.type === "chunk")!.code!;
  server = createServer((request, response) => {
    if (request.url === "/fixture.js") {
      response.writeHead(200, { "Content-Type": "application/javascript" });
      response.end(script);
    } else {
      response.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
      response.end(
        '<html><body><div id="root"></div><script src="/fixture.js"></script></body></html>',
      );
    }
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  origin = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
});
test.afterAll(async () => {
  if (server)
    await new Promise<void>((resolve) => server.close(() => resolve()));
});

test("a video goal survives consumer remounts and resets for a new visit, including browser back", async ({
  page,
}) => {
  await page.addInitScript(() =>
    localStorage.setItem(
      "sinegor.analytics-consent.v1",
      JSON.stringify({
        decision: "accepted",
        savedAt: Date.now(),
        expiresAt: Date.now() + 180 * 86400000,
        textVersion: "1",
        browserId: "2db9f30b-b3a6-4f46-9cb3-212ceea88e05",
      }),
    ),
  );
  await page.route("https://mc.yandex.ru/metrika/tag.js", (route) =>
    route.fulfill({
      contentType: "application/javascript",
      body: `(() => { const queued = window.ym?.a || []; window.__goals = []; window.ym = (...args) => window.__goals.push(args); for (const args of queued) window.ym(...args); })();`,
    }),
  );
  const videoGoals = () =>
    page.evaluate(
      () =>
        ((window as unknown as { __goals?: unknown[][] }).__goals || []).filter(
          (call) =>
            call[1] === "reachGoal" && call[2] === "video_presentation_view",
        ).length,
    );
  await page.goto(origin);
  await page
    .getByRole("button", { name: "Начать просмотр", exact: true })
    .click();
  await expect.poll(videoGoals).toBe(1);
  await page
    .getByRole("button", { name: "Перемонтировать плеер", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Начать просмотр", exact: true })
    .click();
  expect(await videoGoals()).toBe(1);
  await page
    .getByRole("link", { name: "Другая страница", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Вернуться назад", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Начать просмотр", exact: true })
    .click();
  await expect.poll(videoGoals).toBe(2);
});
