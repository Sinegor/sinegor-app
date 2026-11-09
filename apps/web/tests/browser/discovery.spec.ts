import { test, expect } from "@playwright/test";
import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { createRequire } from "node:module";
import type { AddressInfo } from "node:net";

const controller = createRequire(import.meta.url)(
  "../../../cms/src/api/public-content/controllers/public-content.js",
);

test("sitemap tracks Strapi publication and noindex changes without rebuilding SSR", async ({
  request,
  page,
}) => {
  test.setTimeout(60_000);
  type Document = {
    slug: string;
    title: string;
    publishedAt: string | null;
    seo?: { noindex: boolean };
    linkSection?: string;
    linkOrder?: number;
  };
  const documents: Record<string, Document[]> = {
    documents: [],
    pages: ["home", "about", "contacts", "publications", "Case", "case"].map(
      (slug) => ({ slug, title: slug, publishedAt: "2026-10-26T00:00:00Z" }),
    ),
    services: ["ai-analysis", "technical", "TECHNICAL"].map((slug) => ({
      slug,
      title: slug,
      publishedAt: "2026-10-26T00:00:00Z",
    })),
    publications: Array.from({ length: 27 }, (_, i) => ({
      slug: `article-${i}`,
      title: `Article ${i}`,
      publishedAt: "2026-10-26T00:00:00Z",
    })),
  };
  documents.pages.push({
    slug: "hidden",
    title: "Hidden",
    publishedAt: "2026-10-26T00:00:00Z",
    seo: { noindex: true },
  });
  documents.publications.push({
    slug: "draft",
    title: "Draft",
    publishedAt: null,
  });
  documents.pages.push({
    slug: "technical-guide",
    title: "Руководство по обработке",
    publishedAt: "2026-10-26T00:00:00Z",
    linkSection: "technical",
    linkOrder: 2,
  });
  documents.pages.push({
    slug: "_",
    title: "Материал с допустимым slug",
    publishedAt: "2026-10-26T00:00:00Z",
  });
  const scope = globalThis as typeof globalThis & { strapi?: unknown };
  // Keep the real Strapi public controller and serializer; only the DB service is synthetic.
  scope.strapi = {
    documents: (uid: string) => ({
      // The shared SSR layout also reads the optional footer Single Type.
      findFirst: async () => null,
      findMany: async (options: {
        status?: string;
        filters: { slug?: string };
        start: number;
        limit: number;
      }) => {
        const kind = {
          "api::page.page": "pages",
          "api::service.service": "services",
          "api::publication.publication": "publications",
          "api::public-document.public-document": "documents",
        }[uid]!;
        return documents[kind]
          .filter((item) => options.status !== "published" || item.publishedAt)
          .filter(
            (item) =>
              !options.filters.slug || item.slug === options.filters.slug,
          )
          .slice(options.start, options.start + options.limit);
      },
    }),
  };
  let unavailable = false;
  const cms = createServer(async (req, res) => {
    if (unavailable) {
      res.writeHead(503);
      res.end();
      return;
    }
    const url = new URL(req.url!, "http://localhost");
    const [, , , kind, encodedSlug] = url.pathname.split("/");
    const ctx = {
      params: { kind, slug: encodedSlug && decodeURIComponent(encodedSlug) },
      query: Object.fromEntries(url.searchParams),
      body: undefined as unknown,
      set: (name: string, value: string) => res.setHeader(name, value),
      notFound: () => {
        res.statusCode = 404;
      },
    };
    await (encodedSlug ? controller.one(ctx) : controller.list(ctx));
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(ctx.body || { data: null }));
  });
  cms.listen(0, "127.0.0.1");
  await once(cms, "listening");
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
        CMS_ORIGIN: `http://127.0.0.1:${(cms.address() as AddressInfo).port}`,
        PUBLIC_ORIGIN: "https://public.example",
      },
      stdio: "ignore",
    },
  );
  const origin = `http://127.0.0.1:${port}`;
  const readSitemap = async () => {
    const response = await request.get(`${origin}/sitemap.xml`);
    expect(response.status()).toBe(200);
    expect(response.headers()["cache-control"]).toBe("no-store");
    const xml = await response.text();
    expect(xml.startsWith('<?xml version="1.0" encoding="UTF-8"?>')).toBe(true);
    return page.evaluate((source) => {
      const xml = new DOMParser().parseFromString(source, "application/xml");
      if (xml.querySelector("parsererror"))
        throw new Error("Invalid sitemap XML");
      if (
        xml.documentElement.namespaceURI !==
        "http://www.sitemaps.org/schemas/sitemap/0.9"
      )
        throw new Error("Invalid sitemap namespace");
      return [...xml.querySelectorAll("loc")].map((node) => node.textContent!);
    }, xml);
  };
  try {
    await expect
      .poll(async () => {
        try {
          return (await fetch(`${origin}/robots.txt`)).status;
        } catch {
          return 0;
        }
      })
      .toBe(200);
    const urls = await readSitemap();
    await page.goto(`${origin}/publications`);
    await page
      .getByRole("navigation", { name: "Материалы по теме" })
      .getByRole("link", { name: "Материал с допустимым slug" })
      .click();
    await expect(page).toHaveURL(`${origin}/pages/%5F`);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      "Материал с допустимым slug",
    );
    await expect(page.locator('head link[rel="canonical"]')).toHaveAttribute(
      "href",
      "https://public.example/pages/%5F",
    );
    const technical = await request.get(`${origin}/services/technical`);
    expect(await technical.text()).toContain('href="/pages/technical-guide"');
    expect(new Set(urls).size).toBe(urls.length);
    for (const path of [
      "/",
      "/about",
      "/contacts",
      "/documents",
      "/services/ai-analysis",
      "/services/technical",
      "/services/TECHNICAL",
      "/pages/Case",
      "/pages/case",
      "/publications/article-26",
      "/publications?offset=25",
    ])
      expect(urls).toContain(`https://public.example${path}`);
    const graph = new Map<string, string[]>();
    for (const url of urls) {
      expect(url).toMatch(/^https:\/\/public\.example\//);
      expect(url).not.toMatch(
        /localhost|\/pages\/(home|about|contacts|publications)$|\/hidden$|\/draft$|\/(admin|customer|auth|api)(\/|$)/,
      );
      const canonical = new URL(url);
      const response = await request.get(
        `${origin}${canonical.pathname}${canonical.search}`,
        { maxRedirects: 0 },
      );
      expect(response.status(), url).toBe(200);
      const html = await response.text();
      const head = html.split("</head>")[0];
      expect(head.match(/rel="canonical"/g), url).toHaveLength(1);
      expect(head).toContain(`href="${url}"`);
      expect(head).not.toContain("noindex");
      graph.set(
        url,
        await page.evaluate(
          ({ html, base }) => {
            const document = new DOMParser().parseFromString(html, "text/html");
            return [...document.querySelectorAll("a[href]")].map((a) => {
              const target = new URL(a.getAttribute("href")!, base);
              target.hash = "";
              return target.href;
            });
          },
          { html, base: url },
        ),
      );
    }
    const found = new Set<string>();
    const pending = ["https://public.example/"];
    while (pending.length) {
      const url = pending.pop()!;
      if (found.has(url)) continue;
      found.add(url);
      pending.push(
        ...(graph.get(url) || []).filter(
          (to) => graph.has(to) && !found.has(to),
        ),
      );
    }
    expect(urls.filter((url) => !found.has(url))).toEqual([]);

    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(`${origin}/services/technical`);
      await expect(
        page
          .getByRole("navigation", { name: "Материалы по теме" })
          .getByRole("link", { name: "Руководство по обработке" }),
      ).toHaveAttribute("href", "/pages/technical-guide");
      await expect(
        page
          .locator("header")
          .getByRole("link", { name: "Руководство по обработке" }),
      ).toHaveCount(0);
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth),
      ).toBeLessThanOrEqual(width);
      await page.screenshot({
        path: `/tmp/sinegor-links-${width}.png`,
        fullPage: true,
      });
    }
    const guide = documents.pages.find(
      (item) => item.slug === "technical-guide",
    )!;
    guide.linkSection = "about";
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${origin}/services/technical`);
    await expect(
      page.getByRole("navigation", { name: "Материалы по теме" }),
    ).toHaveCount(0);
    await page
      .locator("header")
      .getByRole("link", { name: "Обо мне", exact: true })
      .first()
      .click();
    await expect(
      page
        .getByRole("navigation", { name: "Материалы по теме" })
        .getByRole("link", { name: "Руководство по обработке" }),
    ).toBeVisible();
    guide.seo = { noindex: true };
    expect(await (await request.get(`${origin}/about`)).text()).not.toContain(
      'href="/pages/technical-guide"',
    );
    guide.seo = { noindex: false };
    guide.linkSection = "technical";
    for (const offset of ["1", "24", "26", "50", "999999", "1000000"]) {
      const response = await request.get(
        `${origin}/publications?offset=${offset}`,
        { maxRedirects: 0 },
      );
      expect(response.status(), offset).toBe(404);
      expect((await response.text()).split("</head>")[0]).not.toContain(
        'rel="canonical"',
      );
    }
    for (const [query, target] of [
      ["offset=-25", ""],
      ["offset=bad", ""],
      ["offset=1.2", ""],
      ["offset=0&unused=1", ""],
      ["unused=1", ""],
      ["offset=00025", "?offset=25"],
      ["offset=25&offset=50", "?offset=25"],
      ["offset=25&utm_source=test&unused=1", "?offset=25"],
    ]) {
      const response = await request.get(`${origin}/publications?${query}`, {
        maxRedirects: 0,
      });
      expect(response.status(), query).toBe(308);
      expect(response.headers().location).toBe(
        `https://public.example/publications${target}`,
      );
    }
    expect(
      (await request.head(`${origin}/publications?offset=1000000`)).status(),
    ).toBe(404);
    expect(
      (
        await request.get(`${origin}/publications.data?offset=1000000`)
      ).status(),
    ).toBe(404);
    const dataRedirect = await request.get(
      `${origin}/publications.data?offset=025&unused=1&_routes=routes%2Fpublic%2Fpublications`,
    );
    expect(dataRedirect.status()).toBe(202);
    const dataBody = await dataRedirect.text();
    expect(dataBody).toContain("https://public.example/publications?offset=25");
    expect(dataBody).not.toMatch(/\.data|unused|_routes/);

    await page.goto(`${origin}/publications`);
    await expect(page.locator(".public-grid > .card")).toHaveCount(25);
    await page.getByRole("link", { name: "Далее", exact: true }).click();
    await expect(page).toHaveURL(`${origin}/publications?offset=25`);
    await expect(page.locator(".public-grid > .card")).toHaveCount(2);
    await expect(page.locator('head link[rel="canonical"]')).toHaveAttribute(
      "href",
      "https://public.example/publications?offset=25",
    );
    await expect(
      page.getByRole("link", { name: "Далее", exact: true }),
    ).toHaveCount(0);
    await expect(
      page.getByRole("heading", { name: "Article 25", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Article 0", exact: true }),
    ).toHaveCount(0);

    // Removing the last two articles makes offset=25 nonexistent, without a rebuild.
    const removed = documents.publications.splice(25, 2);
    expect(
      (await request.get(`${origin}/publications?offset=25`)).status(),
    ).toBe(404);
    expect(await readSitemap()).not.toContain(
      "https://public.example/publications?offset=25",
    );
    await page.goto(`${origin}/publications`);
    await expect(page.locator(".public-grid > .card")).toHaveCount(25);
    await expect(
      page.getByRole("link", { name: "Далее", exact: true }),
    ).toHaveCount(0);
    documents.publications.splice(25, 0, ...removed);
    const hidden = await request.get(`${origin}/pages/hidden`);
    expect(hidden.status()).toBe(200);
    expect((await hidden.text()).split("</head>")[0]).toContain(
      'name="robots" content="noindex, follow"',
    );
    expect((await request.get(`${origin}/publications/draft`)).status()).toBe(
      404,
    );

    // The same running SSR process sees each publication change immediately.
    documents.publications.at(-1)!.publishedAt = "2026-10-26T01:00:00Z";
    expect(await readSitemap()).toContain(
      "https://public.example/publications/draft",
    );
    documents.publications.at(-1)!.publishedAt = null;
    expect(await readSitemap()).not.toContain(
      "https://public.example/publications/draft",
    );
    const newPage = {
      slug: "new-page",
      title: "New page",
      publishedAt: "2026-10-26T01:00:00Z",
    };
    documents.pages.push(newPage);
    expect(await readSitemap()).toContain(
      "https://public.example/pages/new-page",
    );
    documents.pages.pop();
    expect(await readSitemap()).not.toContain(
      "https://public.example/pages/new-page",
    );
    documents.services[1].publishedAt = null;
    expect(
      await (await request.get(`${origin}/publications`)).text(),
    ).toContain('href="/pages/technical-guide"');
    expect(await readSitemap()).not.toContain(
      "https://public.example/services/technical",
    );
    expect((await request.get(`${origin}/services/technical`)).status()).toBe(
      404,
    );
    documents.pages.find((item) => item.slug === "about")!.seo = {
      noindex: true,
    };
    expect(await readSitemap()).not.toContain("https://public.example/about");
    documents.pages.find((item) => item.slug === "publications")!.seo = {
      noindex: true,
    };
    expect(
      (await readSitemap()).filter(
        (url) => new URL(url).pathname === "/publications",
      ),
    ).toEqual([]);

    for (const path of ["/sitemap.xml", "/robots.txt"]) {
      const response = await request.head(`${origin}${path}`);
      expect(response.status()).toBe(200);
      expect(await response.body()).toHaveLength(0);
    }
    const robots = await request.get(`${origin}/robots.txt`);
    expect(await robots.text()).toContain(
      "Sitemap: https://public.example/sitemap.xml\n",
    );
    unavailable = true;
    const failed = await request.get(`${origin}/sitemap.xml`);
    expect(failed.status()).toBe(503);
    expect(await failed.text()).not.toContain("<urlset");
    expect((await request.get(`${origin}/robots.txt`)).status()).toBe(200);
  } finally {
    const exited = once(server, "exit");
    server.kill("SIGTERM");
    await exited;
    cms.closeAllConnections();
    await new Promise<void>((resolve) => cms.close(() => resolve()));
    delete scope.strapi;
  }
});
