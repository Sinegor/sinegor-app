import { test, expect } from "@playwright/test";
import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { once } from "node:events";
import type { AddressInfo } from "node:net";
import type { Content } from "../../app/lib/cms";

test("SSR and navigation keep live Open Graph and safe JSON-LD consistent with published CMS content", async ({
  page,
  request,
}) => {
  test.setTimeout(90_000);
  const dangerous = "</script><script>window.__seoInjected=1</script>";
  const documents = new Map<string, Content>([
    ["pages/home", { slug: "home", title: "Главная", sections: [] }],
    [
      "pages/about",
      {
        slug: "about",
        title: "О проекте",
        sections: [
          {
            general: [
              {
                type: "paragraph",
                children: [
                  {
                    type: "text",
                    text: "Проект адвоката Артемьева Дмитрия Валерьевича",
                  },
                ],
              },
            ],
          },
        ],
      },
    ],
    [
      "publications/seo-article",
      {
        slug: "seo-article",
        title: `Статья ${dangerous}`,
        publishedAt: "2026-11-01T12:00:00.000Z",
        sections: [],
        seo: { title: "Поисковый заголовок", description: "Описание статьи" },
        image: {
          url: "/uploads/cover.svg",
          mime: "image/svg+xml",
          alternativeText: "Обложка",
        },
      },
    ],
  ]);
  let unavailable = false;
  const cms = createServer((req, res) => {
    const url = new URL(req.url!, "http://localhost");
    if (url.pathname === "/uploads/cover.svg") {
      res.writeHead(200, { "Content-Type": "image/svg+xml" });
      res.end(
        '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="18"/>',
      );
      return;
    }
    const [, , , kind, encodedSlug] = url.pathname.split("/");
    const slug = encodedSlug && decodeURIComponent(encodedSlug);
    const data = slug
      ? documents.get(`${kind}/${slug}`)
      : [...documents.entries()]
          .filter(([key]) => key.startsWith(`${kind}/`))
          .map(([, value]) => value)
          .slice(Number(url.searchParams.get("offset")) || 0)
          .slice(0, 25);
    res.writeHead(unavailable ? 503 : data ? 200 : 404, {
      "Content-Type": "application/json",
    });
    res.end(JSON.stringify({ data: data || null }));
  });
  cms.listen(0, "127.0.0.1");
  await once(cms, "listening");
  const cmsOrigin = `http://127.0.0.1:${(cms.address() as AddressInfo).port}`;
  const reservation = createServer();
  reservation.listen(0, "127.0.0.1");
  await once(reservation, "listening");
  const port = (reservation.address() as AddressInfo).port;
  await new Promise<void>((resolve) => reservation.close(() => resolve()));
  const server = spawn(process.execPath, ["server/index.js"], {
    env: {
      ...process.env,
      HOST: "127.0.0.1",
      PORT: String(port),
      CMS_ORIGIN: cmsOrigin,
      CMS_MEDIA_ORIGIN: cmsOrigin,
      PUBLIC_ORIGIN: "https://sinegor-lab.website",
    },
    stdio: "ignore",
  });
  const origin = `http://127.0.0.1:${port}`;
  const path = "/publications/seo-article";
  const head = (html: string) => html.split("</head>")[0];
  const schemas = (html: string) =>
    [
      ...head(html).matchAll(
        /<script type="application\/ld\+json">(.*?)<\/script>/gs,
      ),
    ].map((match) => JSON.parse(match[1]) as Record<string, unknown>);
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
    const response = await request.get(origin + path);
    expect(response.status()).toBe(200);
    const html = await response.text();
    expect(head(html)).toContain(
      'property="og:title" content="Поисковый заголовок — SINEGOR LAB"',
    );
    expect(head(html)).toContain(
      `property="og:image" content="${cmsOrigin}/uploads/cover.svg"`,
    );
    expect(head(html)).not.toContain("</script><script>window.__seoInjected");
    expect(
      schemas(html).find((item) => item["@type"] === "Article"),
    ).toMatchObject({
      headline: `Статья ${dangerous}`,
      datePublished: "2026-11-01T12:00:00.000Z",
      url: "https://sinegor-lab.website/publications/seo-article",
    });

    await page.goto(origin + path);
    expect(await page.evaluate(() => "__seoInjected" in window)).toBe(false);
    await expect(page.locator('head meta[property="og:url"]')).toHaveAttribute(
      "content",
      "https://sinegor-lab.website/publications/seo-article",
    );
    await page
      .getByRole("link", { name: "Обо мне", exact: true })
      .first()
      .click();
    await expect(page).toHaveURL(origin + "/about");
    await expect(page.locator('head meta[property="og:url"]')).toHaveCount(1);
    await expect(page.locator('head meta[property="og:url"]')).toHaveAttribute(
      "content",
      "https://sinegor-lab.website/about",
    );
    const afterNavigation = await page
      .locator('head script[type="application/ld+json"]')
      .allTextContents();
    expect(afterNavigation.map((value) => JSON.parse(value)["@type"])).toEqual([
      "BreadcrumbList",
      "Person",
    ]);

    documents.get("publications/seo-article")!.seo!.description =
      "Новая редакция";
    const updated = await (await request.get(origin + path)).text();
    expect(head(updated)).toContain(
      'property="og:description" content="Новая редакция"',
    );
    expect(
      schemas(updated).find((item) => item["@type"] === "Article"),
    ).toHaveProperty("description", "Новая редакция");
    documents.delete("publications/seo-article");
    const missing = await request.get(origin + path);
    expect(missing.status()).toBe(404);
    expect(head(await missing.text())).not.toContain('property="og:');
    expect(schemas(await missing.text())).toEqual([]);
    for (const privatePath of ["/auth/login", "/auth/admin"]) {
      const privateHtml = await (
        await request.get(origin + privatePath)
      ).text();
      expect(head(privateHtml)).not.toContain('property="og:');
      expect(schemas(privateHtml)).toEqual([]);
    }
    unavailable = true;
    const offline = await request.get(origin + "/about");
    expect(offline.status()).toBe(503);
    expect(schemas(await offline.text())).toEqual([]);
  } finally {
    const exited = once(server, "exit");
    server.kill("SIGTERM");
    await exited;
    cms.closeAllConnections();
    await new Promise<void>((resolve) => cms.close(() => resolve()));
  }
});
