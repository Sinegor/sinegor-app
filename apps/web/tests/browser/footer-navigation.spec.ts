import { test, expect, type Locator } from "@playwright/test";
import { createServer, type Server } from "node:http";
import { spawn, type ChildProcess } from "node:child_process";
import { once } from "node:events";
import type { AddressInfo } from "node:net";
import type { FooterData } from "../../app/lib/cms";

let origin: string;
let server: ChildProcess;
let cms: Server;
let data: FooterData;
let unavailable = false;
const empty = () => ({ documents: [], usefulLinks: [] });
const links = (count: number, prefix: string) =>
  Array.from({ length: count }, (_, i) => ({
    label: `${prefix} ${i + 1}`,
    href: `/pages/test-${i + 1}`,
  }));
const footerHtml = (html: string) =>
  html.match(/<footer\b[^>]*>[\s\S]*?<\/footer>/)?.[0] || "";

// This fixture exercises the built SSR via HTTP; browser interception cannot
// replace a server-side CMS fetch. Real Strapi publication is covered by E2E.
test.beforeAll(async () => {
  cms = createServer((request, response) => {
    const path = new URL(request.url!, "http://cms.test").pathname;
    response.setHeader("Content-Type", "application/json");
    if (path === "/api/public-content/footer") {
      response.statusCode = unavailable ? 503 : 200;
      response.end(JSON.stringify({ data: unavailable ? null : data }));
      return;
    }
    const slug = path.split("/")[4];
    response.end(
      JSON.stringify({
        data: slug
          ? {
              slug,
              title: `Страница ${slug}`,
              sections: [],
              body: [],
              publishedAt: "2026-11-06T00:00:00Z",
              revisedOn: "2026-11-06",
            }
          : [],
      }),
    );
  }).listen(0, "127.0.0.1");
  await once(cms, "listening");
  const cmsOrigin = `http://127.0.0.1:${(cms.address() as AddressInfo).port}`;
  const reservation = createServer().listen(0, "127.0.0.1");
  await once(reservation, "listening");
  const port = (reservation.address() as AddressInfo).port;
  await new Promise<void>((resolve) => reservation.close(() => resolve()));
  origin = `http://127.0.0.1:${port}`;
  data = empty();
  server = spawn(process.execPath, ["server/index.js"], {
    env: {
      PATH: process.env.PATH,
      HOME: process.env.HOME,
      NODE_ENV: "production",
      HOST: "127.0.0.1",
      PORT: String(port),
      CMS_ORIGIN: cmsOrigin,
      PUBLIC_ORIGIN: origin,
    },
    stdio: "ignore",
  });
  await expect
    .poll(async () => {
      try {
        return (await fetch(origin + "/pages/test-1")).status;
      } catch {
        return 0;
      }
    })
    .toBe(200);
});

test.afterAll(async () => {
  if (server && server.exitCode === null) {
    const exited = once(server, "exit");
    server.kill("SIGTERM");
    await exited;
  }
  if (cms) await new Promise<void>((resolve) => cms.close(() => resolve()));
});

test.beforeEach(async ({ context }) => {
  data = empty();
  unavailable = false;
  await context.route("**/*", (route) =>
    ["localhost", "127.0.0.1"].includes(new URL(route.request().url()).hostname)
      ? route.continue()
      : route.abort(),
  );
  await context.route("**/api/auth/session", (route) =>
    route.fulfill({ status: 401, json: {} }),
  );
});

test("unconfigured CMS leaves no fixed footer links on public pages or login", async ({
  request,
}) => {
  for (const path of ["/", "/about", "/documents", "/auth/login"]) {
    const response = await request.get(path);
    expect(response.status()).toBe(path === "/documents" ? 503 : 200);
    const footer = footerHtml(await response.text());
    expect(footer).toContain("SINEGOR");
    expect(footer).toContain(">Документы</h2>");
    expect(footer).toContain(">Полезные ссылки</h2>");
    expect(footer).not.toMatch(/<a\b/);
  }
});

async function keyboardDisclosure(
  section: Locator,
  key: "Enter" | "Space",
  page: import("@playwright/test").Page,
) {
  const control = section.locator("summary");
  await control.focus();
  await expect(control).toBeFocused();
  expect(
    await control.evaluate((el) => getComputedStyle(el).outlineStyle),
  ).not.toBe("none");
  await page.keyboard.press(key);
}

for (const width of [1440, 390]) {
  test(`50 links per list stay independent, keyboard accessible and wrap at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    data = {
      documents: links(50, "Документ"),
      usefulLinks: links(50, "Ресурс"),
    };
    data.documents[0].label =
      "Оченьдлинноеназваниебезпробелов".repeat(5) +
      " <script>unsafe()</script>";
    data.usefulLinks[0] = {
      label: "Внешний ресурс",
      href: "https://example.org/reference",
    };
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("console", (message) => {
      if (message.type() === "error") errors.push(message.text());
    });
    const response = await page.goto(origin + "/pages/test-1");
    const ssr = footerHtml(await response!.text());
    expect(ssr.match(/<a /g)).toHaveLength(100);
    const footer = page.getByRole("contentinfo");
    const documents = footer.getByRole("navigation", {
      name: "Документы",
      exact: true,
    });
    const useful = footer.getByRole("navigation", {
      name: "Полезные ссылки",
      exact: true,
    });
    await expect(documents.getByRole("link")).toHaveCount(5);
    await expect(useful.getByRole("link")).toHaveCount(5);
    await expect(documents.getByRole("link").first()).toHaveText(
      data.documents[0].label,
    );
    await expect(useful.getByRole("link").first()).toHaveAttribute(
      "href",
      "https://example.org/reference",
    );
    await expect(
      footer.getByRole("button", { name: "Настройки аналитики", exact: true }),
    ).toBeVisible();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(width);
    await footer.screenshot({
      path: `/tmp/sinegor-t12-22-3/footer-long-${width}.png`,
      animations: "disabled",
    });
    await keyboardDisclosure(documents, "Enter", page);
    await expect(documents.getByRole("link")).toHaveCount(50);
    await expect(documents.locator("summary")).toHaveText(
      "Показать всеСвернуть",
    );
    await expect(documents.locator("summary")).toHaveAccessibleName("Свернуть");
    await expect(useful.getByRole("link")).toHaveCount(5);
    await keyboardDisclosure(useful, "Space", page);
    await expect(useful.getByRole("link")).toHaveCount(50);
    expect(await footer.evaluate((el) => getComputedStyle(el).overflowY)).toBe(
      "visible",
    );
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(width);
    await documents.getByRole("link").last().focus();
    await expect(documents.getByRole("link").last()).toBeInViewport();
    await keyboardDisclosure(documents, "Enter", page);
    await expect(documents.getByRole("link")).toHaveCount(5);
    await expect(useful.getByRole("link")).toHaveCount(50);
    await expect(documents.locator("summary")).toHaveAccessibleName(
      "Показать все",
    );
    expect(errors).toEqual([]);
  });

  test(`short lists use compact columns and analytics stays in the bottom row at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    data = {
      documents: links(3, "Документ"),
      usefulLinks: [{ label: "Об исполнителе", href: "/about" }],
    };
    await page.goto(origin + "/pages/test-1");
    const footer = page.getByRole("contentinfo");
    await expect(footer.locator("details")).toHaveCount(0);
    const columns = footer.locator(".footer-columns");
    const areas = await columns.locator(":scope > *").evaluateAll((els) =>
      els.map((el) => ({
        x: el.getBoundingClientRect().x,
        y: el.getBoundingClientRect().y,
      })),
    );
    if (width === 1440) {
      expect(new Set(areas.map((area) => area.y)).size).toBe(1);
      expect((await footer.boundingBox())!.height).toBeLessThanOrEqual(260);
    } else {
      expect(new Set(areas.map((area) => area.x)).size).toBe(1);
      expect(areas[1].y).toBeGreaterThan(areas[0].y);
    }
    const settings = footer.getByRole("button", {
      name: "Настройки аналитики",
      exact: true,
    });
    await settings.focus();
    await page.keyboard.press("Enter");
    await expect(
      page.getByRole("dialog", { name: "Настройки аналитики" }),
    ).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(settings).toBeFocused();
    await footer.scrollIntoViewIfNeeded();
    await footer.screenshot({
      path: `/tmp/sinegor-t12-22-3/footer-short-${width}.png`,
      animations: "disabled",
    });
    await footer
      .getByRole("link", { name: "Об исполнителе", exact: true })
      .focus();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(origin + "/about");
  });
}

for (const count of [0, 5, 6]) {
  test(`lists of ${count} links have the correct disclosure threshold`, async ({
    page,
  }) => {
    data = { documents: links(count, "Документ"), usefulLinks: [] };
    await page.goto(origin + "/pages/test-1");
    const footer = page.getByRole("contentinfo");
    await expect(footer.getByRole("link")).toHaveCount(Math.min(count, 5));
    await expect(footer.locator("summary")).toHaveCount(count > 5 ? 1 : 0);
  });
}

test("footer endpoint failure leaves the page, analytics settings and subsequent navigation working", async ({
  page,
}) => {
  unavailable = true;
  await page.goto(origin + "/pages/test-1");
  const footer = page.getByRole("contentinfo");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Страница test-1",
  );
  await expect(footer.getByRole("link")).toHaveCount(0);
  await footer
    .getByRole("button", { name: "Настройки аналитики", exact: true })
    .click();
  await expect(
    page.getByRole("dialog", { name: "Настройки аналитики" }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  unavailable = false;
  data.usefulLinks = [
    { label: "Восстановленный ресурс", href: "/pages/test-2" },
  ];
  await page
    .getByRole("navigation", { name: "Основная навигация" })
    .getByRole("link", { name: "Обо мне", exact: true })
    .click();
  await expect(
    footer.getByRole("link", { name: "Восстановленный ресурс" }),
  ).toBeVisible();
});

test("all links remain available with JavaScript disabled and disclosure needs no hydration", async ({
  browser,
}) => {
  data = { documents: links(50, "Документ"), usefulLinks: links(6, "Ресурс") };
  const context = await browser.newContext({ javaScriptEnabled: false });
  try {
    const page = await context.newPage();
    await page.setViewportSize({ width: 390, height: 900 });
    await page.goto(origin + "/pages/test-1");
    const documents = page
      .getByRole("contentinfo")
      .getByRole("navigation", { name: "Документы", exact: true });
    await expect(documents.getByRole("link")).toHaveCount(5);
    await keyboardDisclosure(documents, "Enter", page);
    await expect(documents.getByRole("link")).toHaveCount(50);
    await documents.getByRole("link").last().focus();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(origin + "/pages/test-50");
  } finally {
    await context.close();
  }
});
