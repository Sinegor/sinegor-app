import { test, expect } from "@playwright/test";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { spawn } from "node:child_process";
import { once } from "node:events";
import type { AddressInfo } from "node:net";

// A local CMS stub exercises the actual SSR loader and client revalidation,
// without changing published content or requiring a CMS database.
test("home reloads its video after CMS replacement and removal", async ({
  page,
}) => {
  let version: number | null = 1;
  let offline = false;
  const movie = await readFile("public/media/sinegor-lab-preview.mp4");
  const cms = createServer((request, response) => {
    const path = new URL(request.url!, "http://localhost").pathname;
    if (offline) {
      response.writeHead(503).end();
      return;
    }
    if (path.startsWith("/uploads/")) {
      if (path === "/uploads/2.mp4") {
        response.writeHead(404).end();
        return;
      }
      response.writeHead(200, {
        "Content-Type": "video/mp4",
        "Content-Length": movie.length,
      });
      response.end(movie);
      return;
    }
    response.setHeader("Content-Type", "application/json");
    if (path === "/api/public-content/pages/home") {
      response.end(
        JSON.stringify({
          data: {
            slug: "home",
            title: `Видео ${version ?? "удалено"}`,
            sections: [],
            video: version
              ? { url: `/uploads/${version}.mp4`, mime: "video/mp4" }
              : null,
            videoCaption: "Презентация из CMS",
          },
        }),
      );
    } else if (path === "/api/public-content/pages/about") {
      response.writeHead(404).end("{}");
    } else {
      response.end(JSON.stringify({ data: [] }));
    }
  });
  cms.listen(0, "127.0.0.1");
  await once(cms, "listening");
  const cmsOrigin = `http://127.0.0.1:${(cms.address() as AddressInfo).port}`;
  const server = spawn(
    process.execPath,
    ["node_modules/@react-router/serve/bin.js", "./build/server/index.js"],
    {
      env: {
        ...process.env,
        HOST: "127.0.0.1",
        PORT: "3104",
        CMS_ORIGIN: cmsOrigin,
        CMS_MEDIA_ORIGIN: cmsOrigin,
      },
      stdio: "ignore",
    },
  );
  const origin = "http://127.0.0.1:3104";
  try {
    await expect
      .poll(async () => {
        try {
          return (await fetch(origin)).status;
        } catch {
          return 0;
        }
      })
      .toBe(200);
    await page.goto(origin);
    const video = page.locator("video");
    await expect
      .poll(() =>
        video.evaluate((element: HTMLVideoElement) => element.currentSrc),
      )
      .toBe(`${cmsOrigin}/uploads/1.mp4`);
    await expect(video).toHaveAttribute("controls", "");
    await expect(video).toHaveAttribute("playsinline", "");
    await expect(page.locator("figcaption")).toHaveText("Презентация из CMS");
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 900 });
      await video.evaluate(async (element: HTMLVideoElement) => {
        element.currentTime = 0;
        element.muted = false;
        element.volume = 0.5;
        await element.play();
      });
      await expect
        .poll(() =>
          video.evaluate((element: HTMLVideoElement) => element.currentTime),
        )
        .toBeGreaterThan(0);
      await video.evaluate((element: HTMLVideoElement) => {
        element.pause();
        element.currentTime = element.duration / 2;
      });
      await expect
        .poll(() =>
          video.evaluate((element: HTMLVideoElement) => element.seeking),
        )
        .toBe(false);
      expect(
        await video.evaluate((element: HTMLVideoElement) => element.muted),
      ).toBe(false);
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth),
      ).toBeLessThanOrEqual(width);
    }
    version = 2;
    await page.locator(".brand").click();
    await expect(
      page.getByRole("heading", { name: "Видео 2", exact: true }),
    ).toBeVisible();
    await expect(page.getByRole("alert")).toContainText(
      "Не удалось загрузить видео",
    );
    await expect(
      page.getByRole("link", { name: "Открыть видео отдельно" }),
    ).toHaveAttribute("href", `${cmsOrigin}/uploads/2.mp4`);
    version = 3;
    await page.locator(".brand").click();
    await expect(
      page.getByRole("heading", { name: "Видео 3", exact: true }),
    ).toBeVisible();
    await expect
      .poll(() =>
        video.evaluate((element: HTMLVideoElement) => element.currentSrc),
      )
      .toBe(`${cmsOrigin}/uploads/3.mp4`);
    await expect(page.getByRole("alert")).toHaveCount(0);
    version = null;
    await page.locator(".brand").click();
    await expect(
      page.getByRole("heading", { name: "Видео удалено", exact: true }),
    ).toBeVisible();
    await expect(video.locator("source")).toHaveCount(0);
    await expect(video).not.toHaveAttribute("controls");
    await expect(page.locator(".hero-video").getByRole("status")).toContainText(
      "Видеопрезентация пока недоступна",
    );
    expect(
      await video.evaluate((element: HTMLVideoElement) => element.currentSrc),
    ).toBe("");
    await expect(page.getByRole("alert")).toHaveCount(0);
    offline = true;
    const unavailable = await page.goto(origin);
    expect(unavailable?.status()).toBe(503);
    await expect(page.locator("h1")).toHaveText("Не удалось открыть страницу");
    await page.route("**/api/auth/session", (route) =>
      route.fulfill({ status: 401, json: {} }),
    );
    await page.goto(`${origin}/auth/admin`);
    await expect(
      page.getByRole("heading", { name: "Вход администратора" }),
    ).toBeVisible();
  } finally {
    const exited = once(server, "exit");
    server.kill("SIGTERM");
    await exited;
    cms.closeAllConnections();
    await new Promise<void>((resolve, reject) =>
      cms.close((error) => (error ? reject(error) : resolve())),
    );
  }
});
