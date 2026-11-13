import { test, expect } from "@playwright/test";
import { createServer, type Server } from "node:http";
import { spawn, type ChildProcess } from "node:child_process";
import { once } from "node:events";
import type { AddressInfo } from "node:net";

let cms: Server;
let server: ChildProcess;
let cmsSite: string;
const isWideArt = (url: string) =>
  /\/AI Core and Holographic Justice(?:-[^/]+)?\.png$/.test(
    decodeURIComponent(new URL(url).pathname),
  );

test.beforeAll(async () => {
  // Cover the real CMS-backed home branch without opening a database.
  cms = createServer((req, res) => {
    res.setHeader("Content-Type", "application/json");
    const path = new URL(req.url!, "http://localhost").pathname;
    if (path === "/api/public-content/pages/home")
      res.end(
        JSON.stringify({
          data: {
            slug: "home",
            title: "Исследование юридических документов — CMS",
            summary: "Поиск, сопоставление и систематизация информации.",
            sections: [],
          },
        }),
      );
    else if (path === "/api/public-content/pages/about")
      res.writeHead(404).end(JSON.stringify({ data: null }));
    else res.end(JSON.stringify({ data: [] }));
  });
  cms.listen(0, "127.0.0.1");
  await once(cms, "listening");
  const cmsOrigin = `http://127.0.0.1:${(cms.address() as AddressInfo).port}`;
  const reservation = createServer();
  reservation.listen(0, "127.0.0.1");
  await once(reservation, "listening");
  const port = (reservation.address() as AddressInfo).port;
  await new Promise<void>((resolve) => reservation.close(() => resolve()));
  cmsSite = `http://127.0.0.1:${port}`;
  server = spawn(process.execPath, ["server/index.js"], {
    env: {
      ...process.env,
      HOST: "127.0.0.1",
      PORT: String(port),
      CMS_ORIGIN: cmsOrigin,
      CMS_MEDIA_ORIGIN: cmsOrigin,
    },
    stdio: "ignore",
  });
  await expect
    .poll(async () => {
      try {
        return (await fetch(cmsSite)).status;
      } catch {
        return 0;
      }
    })
    .toBe(200);
});

test.afterAll(async () => {
  if (server) {
    const exited = once(server, "exit");
    server.kill("SIGTERM");
    await exited;
  }
  if (cms) {
    cms.closeAllConnections();
    await new Promise<void>((resolve) => cms.close(() => resolve()));
  }
});

for (const source of ["fallback", "cms"] as const) {
  for (const javaScriptEnabled of [false, true]) {
    for (const width of [390, 767, 768, 1440]) {
      test(`${source}, JavaScript ${javaScriptEnabled}, ${width}px: only visible desktop artwork is requested`, async ({
        browser,
        baseURL,
      }, info) => {
        const context = await browser.newContext({
          viewport: { width, height: 900 },
          javaScriptEnabled,
        });
        const requests: string[] = [];
        context.on("request", (request) => {
          if (isWideArt(request.url())) requests.push(request.url());
        });
        try {
          const page = await context.newPage();
          const response = await page.goto(
            source === "cms" ? cmsSite : baseURL!,
          );
          expect(response?.status()).toBe(200);
          await page.evaluate(() => document.fonts.ready);
          await expect(page.locator(".public-hero h1")).toHaveText(
            source === "cms"
              ? "Исследование юридических документов — CMS"
              : "Исследование юридических документов",
          );
          const art = page.locator(".public-hero .hero-art");
          if (width >= 768) {
            await expect(art).toBeVisible();
            await expect(art).toHaveJSProperty("naturalWidth", 1774);
            expect(requests.length).toBeGreaterThan(0);
          } else {
            await expect(art).toBeHidden();
            // Include initial SSR discovery and subsequent hydration requests.
            await page.waitForTimeout(500);
          }
          await page.screenshot({
            path: info.outputPath("page.png"),
            fullPage: true,
            animations: "disabled",
            mask: [page.locator("video")],
          });
          const hero = await page.locator(".public-hero").boundingBox();
          const copy = await page.locator(".public-hero > div").boundingBox();
          const video = await page.locator(".hero-video").boundingBox();
          expect(hero).not.toBeNull();
          expect(copy).not.toBeNull();
          expect(video).not.toBeNull();
          if (width >= 768) {
            expect(copy!.x).toBeLessThan(video!.x);
            expect(copy!.y).toBeLessThan(video!.y + video!.height);
            expect(video!.y).toBeLessThan(copy!.y + copy!.height);
          } else {
            expect(copy!.y).toBeCloseTo(hero!.y, 1);
          }
          await info.attach("wide-art-network", {
            body: JSON.stringify({
              source,
              javaScriptEnabled,
              width,
              requests,
            }),
            contentType: "application/json",
          });
          if (width <= 767) expect(requests).toEqual([]);
        } finally {
          await context.close();
        }
      });
    }
  }
}

test("a mobile viewport requests the original artwork only after becoming desktop-sized", async ({
  browser,
  baseURL,
}) => {
  const context = await browser.newContext({
    viewport: { width: 767, height: 900 },
  });
  const requests: string[] = [];
  context.on("request", (request) => {
    if (isWideArt(request.url())) requests.push(request.url());
  });
  try {
    const page = await context.newPage();
    await page.goto(baseURL!);
    await page.waitForTimeout(500);
    expect(requests).toEqual([]);
    await page.setViewportSize({ width: 768, height: 900 });
    await expect(page.locator(".public-hero .hero-art")).toBeVisible();
    await expect(page.locator(".public-hero .hero-art")).toHaveJSProperty(
      "naturalWidth",
      1774,
    );
    expect(requests.length).toBeGreaterThan(0);
    await page.setViewportSize({ width: 767, height: 900 });
    await expect(page.locator(".public-hero .hero-art")).toBeHidden();
  } finally {
    await context.close();
  }
});
