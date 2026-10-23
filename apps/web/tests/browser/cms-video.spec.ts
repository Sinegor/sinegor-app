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
  const movie = await readFile("public/media/sinegor-lab-preview.mp4");
  const cms = createServer((request, response) => {
    const path = new URL(request.url!, "http://localhost").pathname;
    if (path.startsWith("/uploads/")) {
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
    version = 2;
    await page.locator(".brand").click();
    await expect(
      page.getByRole("heading", { name: "Видео 2", exact: true }),
    ).toBeVisible();
    await expect
      .poll(() =>
        video.evaluate((element: HTMLVideoElement) => element.currentSrc),
      )
      .toBe(`${cmsOrigin}/uploads/2.mp4`);
    version = null;
    await page.locator(".brand").click();
    await expect(
      page.getByRole("heading", { name: "Видео удалено", exact: true }),
    ).toBeVisible();
    await expect
      .poll(() =>
        video.evaluate((element: HTMLVideoElement) => element.currentSrc),
      )
      .toBe(`${origin}/media/sinegor-lab-preview.mp4`);
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
