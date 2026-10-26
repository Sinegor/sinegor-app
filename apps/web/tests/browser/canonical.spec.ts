import { test, expect } from "@playwright/test";
import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { once } from "node:events";
import type { AddressInfo } from "node:net";
import type { Content } from "../../app/lib/cms";

test("SSR canonical follows runtime origin, publication state and case-sensitive CMS documents", async ({
  request,
  page,
}) => {
  test.setTimeout(60_000);
  const documents = new Map<string, Content>();
  const publish = (kind: string, slug: string) =>
    documents.set(`${kind}/${slug}`, {
      slug,
      title: `${kind}: ${slug}`,
      sections: [{ text: `Document ${kind}/${slug}` }],
      seo: { title: `SEO ${slug}`, description: `Description ${slug}` },
    });
  for (const slug of [
    "home",
    "about",
    "contacts",
    "publications",
    "About",
    "ABOUT",
    "Case",
    "case",
  ])
    publish("pages", slug);
  for (const slug of ["ai-analysis", "technical", "TECHNICAL", "Case", "case"])
    publish("services", slug);
  for (const slug of [
    "Case",
    "case",
    ...Array.from({ length: 24 }, (_, i) => `article-${i}`),
  ])
    publish("publications", slug);

  let unavailable = false;
  const cms = createServer((req, res) => {
    const url = new URL(req.url!, "http://localhost");
    const parts = url.pathname.split("/");
    const kind = parts[3];
    const slug = parts[4] && decodeURIComponent(parts[4]);
    const content = slug
      ? documents.get(`${kind}/${slug}`)
      : [...documents.entries()]
          .filter(([key]) => key.startsWith(`${kind}/`))
          .map(([, value]) => value)
          .slice(Number(url.searchParams.get("offset")) || 0)
          .slice(0, 25);
    res.writeHead(unavailable ? 503 : content ? 200 : 404, {
      "Content-Type": "application/json",
    });
    res.end(JSON.stringify({ data: content || null }));
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
        PUBLIC_ORIGIN: "https://sinegor.example",
      },
      stdio: "ignore",
    },
  );
  const origin = `http://127.0.0.1:${port}`;
  const canonicals = (html: string) =>
    html.split("</head>")[0].match(/<link\b[^>]*rel="canonical"[^>]*>/g) || [];
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

    for (const path of [
      "/",
      "/about",
      "/contacts",
      "/publications",
      "/services/ai-analysis",
      "/services/technical",
      "/services/TECHNICAL",
      "/pages/Case",
      "/pages/case",
      "/pages/About",
      "/pages/ABOUT",
      "/services/Case",
      "/services/case",
      "/publications/Case",
      "/publications/case",
      "/publications?offset=25",
    ]) {
      const response = await request.get(`${origin}${path}`);
      expect(response.status(), path).toBe(200);
      const html = await response.text();
      expect(canonicals(html), path).toEqual([
        `<link rel="canonical" href="https://sinegor.example${path}"/>`,
      ]);
      expect(response.headers().link || "").not.toMatch(/canonical/i);
      if (
        path.includes("/Case") ||
        path.includes("/case") ||
        path.includes("/ABOUT")
      )
        expect(html).toContain(`Document ${path.slice(1)}`);
    }

    for (const [from, to] of [
      ["/about/", "/about"],
      ["/ABOUT", "/about"],
      ["/pages/about", "/about"],
      ["/PAGES/home/", "/"],
      ["/pages/contacts", "/contacts"],
      ["/pages/publications/?offset=025", "/publications?offset=25"],
      ["/SERVICES/ai-analysis/", "/services/ai-analysis"],
      ["/Publications/Case/", "/publications/Case"],
      ["/publications?offset=0", "/publications"],
      ["/publications?offset=bad", "/publications"],
    ]) {
      for (const method of ["GET", "HEAD"]) {
        const response = await request.fetch(`${origin}${from}`, {
          method,
          maxRedirects: 0,
        });
        expect(response.status(), from).toBe(308);
        expect(response.headers().location).toBe(
          `https://sinegor.example${to}`,
        );
        const target = await request.get(`${origin}${to}`, { maxRedirects: 0 });
        expect(target.status()).toBe(200);
      }
    }

    const tracked = await request.get(`${origin}/about?utm_source=test`);
    expect(canonicals(await tracked.text())).toEqual([
      '<link rel="canonical" href="https://sinegor.example/about"/>',
    ]);
    // Single-fetch encodes redirects as 202 responses for the browser router.
    for (const path of [
      "/ABOUT.data",
      "/about/_.data",
      "/pages/about.data",
      "/PAGES/about.data?_routes=routes%2Fpublic%2Fpage",
    ]) {
      const response = await request.get(`${origin}${path}`, {
        maxRedirects: 0,
      });
      expect(response.status(), path).toBe(202);
      const body = await response.text();
      expect(body).toContain("https://sinegor.example/about");
      expect(body).toContain("308");
      expect(body).not.toContain(".data");
      expect(body).not.toContain("_routes");
    }
    expect((await request.get(`${origin}/about.data`)).status()).toBe(200);
    for (const path of [
      "/pages/newly-published",
      "/publications/newly-published",
    ]) {
      expect((await request.get(`${origin}${path}`)).status()).toBe(404);
      const [kind, slug] = path.slice(1).split("/");
      publish(kind, slug);
      const response = await request.get(`${origin}${path}`);
      expect(response.status()).toBe(200);
      expect(canonicals(await response.text())).toEqual([
        `<link rel="canonical" href="https://sinegor.example${path}"/>`,
      ]);
    }

    // Parent loader data can survive navigation; canonical must follow the leaf URL.
    await page.goto(`${origin}/about`);
    await page
      .getByRole("link", { name: "Публикации", exact: true })
      .first()
      .click();
    await expect(page).toHaveURL(`${origin}/publications`);
    await expect(page.locator('head link[rel="canonical"]')).toHaveCount(1);
    await expect(page.locator('head link[rel="canonical"]')).toHaveAttribute(
      "href",
      "https://sinegor.example/publications",
    );
    await page.getByRole("link", { name: "Далее", exact: true }).click();
    await expect(page.locator('head link[rel="canonical"]')).toHaveAttribute(
      "href",
      "https://sinegor.example/publications?offset=25",
    );
    await page.getByRole("link", { name: "Назад", exact: true }).click();
    await expect(page).toHaveURL(`${origin}/publications`);
    await expect(page.locator('head link[rel="canonical"]')).toHaveAttribute(
      "href",
      "https://sinegor.example/publications",
    );

    for (const path of [
      "/unknown",
      "/pages/missing",
      "/publications/missing",
      "/auth/login",
      "/auth/admin",
      "/customer/orders",
      "/admin",
    ]) {
      const response = await request.get(`${origin}${path}`);
      expect(canonicals(await response.text()), path).toHaveLength(0);
    }
    unavailable = true;
    const response = await request.get(`${origin}/about`);
    expect(response.status()).toBe(503);
    expect(canonicals(await response.text())).toHaveLength(0);
  } finally {
    const exited = once(server, "exit");
    server.kill("SIGTERM");
    await exited;
    cms.closeAllConnections();
    await new Promise<void>((resolve) => cms.close(() => resolve()));
  }
});
