import { test as base, expect, type Locator } from "@playwright/test";
import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { once } from "node:events";
import type { AddressInfo } from "node:net";
import type { Content, ImageLayout, Media } from "../../app/lib/cms";

const image = (name = "wide", width = 1600, height = 900): Media => ({
  url: `/uploads/${name}.svg`,
  mime: "image/svg+xml",
  alternativeText: "Обложка",
  width,
  height,
});
const initial = (): Content => ({
  slug: "illustrated",
  title: "Материал с иллюстрациями",
  summary: "Вводный текст материала.",
  image: image(),
  imageLayout: { position: "top", size: "medium" },
  sections: [
    {
      heading: "Раздел материала",
      text: "Первый абзац.\n\nВторой абзац сохраняется.",
      image: { ...image(), alternativeText: "Иллюстрация раздела" },
      imageLayout: {
        position: "left",
        size: "small",
        caption: "Подпись к разделу",
      },
    },
  ],
});

// Exercise real SSR and CSS with synthetic public content, without a working CMS DB.
const test = base.extend<{
  site: { origin: string; cmsOrigin: string; set: (data: Content) => void };
}>({
  site: async ({}, use) => {
    let content = initial();
    const cms = createServer((request, response) => {
      const path = new URL(request.url!, "http://localhost").pathname;
      if (path.startsWith("/uploads/")) {
        const [w, h] = path.includes("tall")
          ? [1200, 3600]
          : path.includes("tiny")
            ? [64, 32]
            : [1600, 900];
        response.writeHead(200, { "Content-Type": "image/svg+xml" });
        response.end(
          `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><rect width="100%" height="100%" fill="#29343a"/><path d="M0 0L${w} ${h}M${w} 0L0 ${h}" stroke="#9de0c4" stroke-width="8"/><circle cx="${w / 2}" cy="${h / 2}" r="${Math.min(w, h) / 4}" fill="#9de0c4"/></svg>`,
        );
        return;
      }
      response.setHeader("Content-Type", "application/json");
      const parts = path.split("/").filter(Boolean);
      response.end(
        JSON.stringify({ data: parts.length === 3 ? [content] : content }),
      );
    });
    cms.listen(0, "127.0.0.1");
    await once(cms, "listening");
    const cmsOrigin = `http://127.0.0.1:${(cms.address() as AddressInfo).port}`;
    const reservation = createServer();
    reservation.listen(0, "127.0.0.1");
    await once(reservation, "listening");
    const port = (reservation.address() as AddressInfo).port;
    await new Promise<void>((resolve) => reservation.close(() => resolve()));
    const server = spawn(
      process.execPath,
      ["node_modules/@react-router/serve/bin.js", "./build/server/index.js"],
      {
        env: {
          ...process.env,
          HOST: "127.0.0.1",
          PORT: String(port),
          CMS_ORIGIN: cmsOrigin,
          CMS_MEDIA_ORIGIN: cmsOrigin,
        },
        stdio: "ignore",
      },
    );
    const origin = `http://127.0.0.1:${port}`;
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
      await use({
        origin,
        cmsOrigin,
        set: (data) => {
          content = data;
        },
      });
    } finally {
      const exited = once(server, "exit");
      server.kill("SIGTERM");
      await exited;
      cms.closeAllConnections();
      await new Promise<void>((resolve) => cms.close(() => resolve()));
    }
  },
});

async function box(locator: Locator) {
  await expect(locator).toBeVisible();
  return (await locator.boundingBox())!;
}

test("CMS sizes, alignment and side layouts respect image and container geometry", async ({
  page,
  site,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const root = page.locator(
    ".public-prose > .content-media > .content-media__layout",
  );
  const picture = root.locator(":scope > figure > img");
  const figure = root.locator(":scope > figure");
  const body = root.locator(":scope > .content-media__body");
  const setLayout = async (layout: ImageLayout, media = image()) => {
    site.set({ ...initial(), image: media, imageLayout: layout });
    await page.goto(`${site.origin}/about`);
    await expect(picture).toHaveJSProperty("complete", true);
  };
  for (const [size, width] of [
    ["small", 240],
    ["medium", 400],
    ["large", 640],
    ["full", 850],
  ] as const) {
    await setLayout({ size });
    expect((await box(picture)).width).toBeCloseTo(width, 0);
    expect((await box(picture)).height).toBeLessThanOrEqual(480);
  }
  for (const alignment of ["left", "center", "right"] as const) {
    await setLayout({ size: "small", alignment });
    const imageBox = await box(picture),
      parentBox = await box(root);
    const expectedX =
      alignment === "left"
        ? parentBox.x
        : alignment === "right"
          ? parentBox.x + parentBox.width - imageBox.width
          : parentBox.x + (parentBox.width - imageBox.width) / 2;
    expect(imageBox.x).toBeCloseTo(expectedX, 0);
  }
  for (const position of ["left", "right"] as const) {
    await setLayout({ position, size: "large" });
    const imageBox = await box(picture),
      textBox = await box(body),
      parentBox = await box(root);
    expect(imageBox.width).toBeLessThanOrEqual(parentBox.width * 0.45 + 1);
    expect(Math.abs(imageBox.y - textBox.y)).toBeLessThan(1);
    expect(
      position === "left" ? imageBox.x < textBox.x : imageBox.x > textBox.x,
    ).toBe(true);
    // The section inside the now narrow text column stacks independently.
    const nested = body.locator(".content-media__layout");
    const nestedImage = await box(nested.locator(":scope > figure"));
    const nestedText = await box(
      nested.locator(":scope > .content-media__body"),
    );
    expect(nestedText.y).toBeGreaterThanOrEqual(
      nestedImage.y + nestedImage.height,
    );
  }
  await setLayout({ size: "large" }, image("tall", 1200, 3600));
  expect((await box(picture)).height).toBeCloseTo(480, 0);
  expect((await box(picture)).height / (await box(picture)).width).toBeCloseTo(
    3,
    2,
  );
  await setLayout({ size: "full" }, image("tiny", 64, 32));
  expect((await box(picture)).width).toBe(64);
  expect((await box(picture)).height).toBe(32);
  // A caption can widen the figure beyond a tiny or height-limited image.
  for (const media of [image("tiny", 64, 32), image("tall", 1200, 3600)]) {
    for (const alignment of ["left", "center", "right"] as const) {
      await setLayout(
        {
          size: "medium",
          alignment,
          caption:
            "Подробная подпись к иллюстрации, которая шире самого изображения.",
        },
        media,
      );
      const imageBox = await box(picture),
        parentBox = await box(root);
      const expectedX =
        alignment === "left"
          ? parentBox.x
          : alignment === "right"
            ? parentBox.x + parentBox.width - imageBox.width
            : parentBox.x + (parentBox.width - imageBox.width) / 2;
      expect(imageBox.x).toBeCloseTo(expectedX, 0);
    }
  }
  for (const width of [320, 390, 767]) {
    await page.setViewportSize({ width, height: 1000 });
    await setLayout({ position: "right" });
    const imageBox = await box(figure),
      textBox = await box(body);
    if ((await box(root)).width < 600)
      expect(textBox.y).toBeGreaterThanOrEqual(imageBox.y + imageBox.height);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(width);
  }
  site.set({
    ...initial(),
    image: null,
    sections: [
      { text: "Текст без иллюстраций", image: { ...image(), url: "" } },
    ],
  });
  await page.goto(`${site.origin}/about`);
  await expect(page.locator(".content-media")).toHaveCount(0);
  await expect(page.getByText("Текст без иллюстраций")).toBeVisible();
});

test("all public routes render CMS section images and retain page actions and video", async ({
  page,
  site,
}) => {
  test.setTimeout(60_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  site.set({
    ...initial(),
    imageLayout: {
      position: "right",
      size: "small",
      caption: "Иллюстрация материала",
    },
  });
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    for (const path of [
      "/",
      "/about",
      "/contacts",
      "/publications",
      "/publications/illustrated",
      "/services/ai-analysis",
      "/services/technical",
      "/services/illustrated",
      "/pages/illustrated",
    ]) {
      const response = await page.goto(`${site.origin}${path}`);
      expect(response?.status()).toBe(200);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await expect(page.getByAltText("Иллюстрация раздела")).toBeVisible();
      await expect(
        page.getByText("Второй абзац сохраняется.", { exact: true }),
      ).toBeVisible();
      if (path === "/") {
        await expect(page.locator("video")).toHaveAttribute(
          "poster",
          `${site.cmsOrigin}/uploads/wide.svg`,
        );
        await expect(
          page.getByRole("link", { name: "Запросить консультацию" }),
        ).toBeVisible();
      } else {
        await expect(page.getByAltText("Обложка").first()).toBeVisible();
      }
      if (path === "/contacts")
        await expect(page.getByLabel("Ваш email")).toBeVisible();
      if (path === "/publications" || path === "/") {
        const card = page.locator(".public-grid > .card .content-media__image");
        for (let i = 0; i < (await card.count()); i++)
          expect((await box(card.nth(i))).height).toBeLessThanOrEqual(240);
        await expect(
          page.getByRole("link", { name: "Читать статью" }),
        ).toBeVisible();
      }
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth),
      ).toBeLessThanOrEqual(width);
      if (["/", "/about", "/contacts", "/publications"].includes(path)) {
        await page.screenshot({
          path: `/tmp/sinegor-image-analysis/screenshots/${width}-${path.replaceAll("/", "_") || "home"}.png`,
          fullPage: true,
        });
      }
    }
  }
  expect(errors).toEqual([]);
});
