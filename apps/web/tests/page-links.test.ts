import { afterEach, expect, it, vi } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router";
import type { Content, PageLinkSection } from "../app/lib/cms";
import { buildPageLinks } from "../app/lib/page-links.server";
import { PageLinks } from "../app/components/page-links";
import { loader, shouldRevalidate } from "../app/layouts/public";
import { ArticleCards } from "../app/components/cms-content";
import Home, { loader as homeLoader } from "../app/routes/public/home";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});
const page = (
  slug: string,
  linkSection?: PageLinkSection,
  linkOrder = 0,
): Content => ({
  slug,
  title: slug,
  publishedAt: "2026-10-26T00:00:00Z",
  sections: [],
  linkSection,
  linkOrder,
});

it("places published SEO pages in their selected sections with canonical case-sensitive paths", () => {
  const pages = [
    page("home"),
    page("about"),
    page("contacts"),
    page("publications"),
    page("Guide", "technical", 2),
    page("guide", "technical", 1),
    page("legacy"),
  ];
  const services = [page("ai-analysis"), page("technical")];
  expect(buildPageLinks("technical", pages, services)).toEqual([
    { to: "/pages/guide", title: "guide" },
    { to: "/pages/Guide", title: "Guide" },
  ]);
  expect(buildPageLinks("publications", pages, services)).toEqual([
    { to: "/pages/legacy", title: "legacy" },
  ]);
});

it.each(["home", "about", "contacts", "ai-analysis", "technical"] as const)(
  "uses the publications catalogue if the selected host %s is unpublished",
  (section) => {
    expect(
      buildPageLinks("publications", [page("guide", section)], []),
    ).toEqual([{ to: "/pages/guide", title: "guide" }]);
    expect(buildPageLinks(section, [page("guide", section)], [])).toEqual([]);
  },
);

it("omits drafts, noindex pages, fixed page aliases and duplicate or unrouteable targets", () => {
  const pages = [
    page("home"),
    page("about"),
    page("contacts"),
    page("publications"),
    { ...page("draft"), publishedAt: undefined },
    { ...page("hidden"), seo: { noindex: true } },
    page("test.data"),
    page(".."),
    page("a/b"),
    page("About"),
    page("About"),
  ];
  expect(buildPageLinks("publications", pages, [])).toEqual([
    { to: "/pages/About", title: "About" },
  ]);
});

it("renders ordinary SSR anchors with escaped descriptive text and no empty block", () => {
  const html = renderToStaticMarkup(
    createElement(
      MemoryRouter,
      null,
      createElement(PageLinks, {
        links: [{ to: "/pages/Guide", title: "Тема <script>" }],
      }),
    ),
  );
  expect(html).toContain('href="/pages/Guide"');
  expect(html).toContain("Тема &lt;script&gt;");
  expect(html).toContain("Материалы по теме");
  expect(renderToStaticMarkup(createElement(PageLinks, { links: [] }))).toBe(
    "",
  );
});

it("enumerates all CMS pages for SSR data requests rather than only the first 25", async () => {
  vi.stubEnv("CMS_ORIGIN", "http://cms.internal");
  const pages = Array.from({ length: 26 }, (_, i) => page(`guide-${i}`));
  vi.stubGlobal("fetch", async (input: URL) => {
    const url = new URL(input);
    const offset = Number(url.searchParams.get("offset"));
    return new Response(
      JSON.stringify({
        data: url.pathname.endsWith("/pages")
          ? pages.slice(offset, offset + 25)
          : [],
      }),
    );
  });
  const data = await loader({
    request: new Request("http://site.local/publications.data?offset=25"),
  } as Parameters<typeof loader>[0]);
  expect(data.pageLinks).toHaveLength(26);
  expect(data.pageLinks).toContainEqual({
    to: "/pages/guide-25",
    title: "guide-25",
  });
});

it("does not make auth routes depend on CMS availability", async () => {
  vi.stubEnv("CMS_ORIGIN", "http://unavailable.internal");
  vi.stubGlobal("fetch", async () => {
    throw new Error("offline");
  });
  const data = await loader({
    request: new Request("http://site.local/auth/login.data"),
  } as Parameters<typeof loader>[0]);
  expect(data.pageLinks).toEqual([]);
});

it("reloads related links when moving between sections or entering from auth", () => {
  const check = (from: string, to: string) =>
    shouldRevalidate({
      currentUrl: new URL(from, "http://site.local"),
      nextUrl: new URL(to, "http://site.local"),
      defaultShouldRevalidate: false,
    } as Parameters<typeof shouldRevalidate>[0]);
  expect(check("/auth/login", "/publications")).toBe(true);
  expect(check("/publications", "/services/technical")).toBe(true);
  expect(check("/services/technical", "/about")).toBe(true);
  expect(check("/about", "/auth/admin")).toBe(true);
});

it("renders canonical article links without turning an unrouteable slug into a self-link", () => {
  const html = renderToStaticMarkup(
    createElement(
      MemoryRouter,
      null,
      createElement(ArticleCards, {
        articles: [page("Case"), page("unrouteable.data")],
      }),
    ),
  );
  expect(html).toContain('href="/publications/Case"');
  expect(html).not.toContain("unrouteable.data");
  expect(html.match(/<a\b/g)).toHaveLength(1);
});

it("exposes services beyond the first CMS batch as ordinary homepage HTML links", async () => {
  vi.stubEnv("CMS_ORIGIN", "http://cms.internal");
  const services = Array.from({ length: 26 }, (_, i) => page(`service-${i}`));
  vi.stubGlobal("fetch", async (input: URL) => {
    const url = new URL(input);
    const offset = Number(url.searchParams.get("offset"));
    const data = url.pathname.endsWith("/services")
      ? services.slice(offset, offset + 25)
      : url.pathname.endsWith("/home")
        ? page("home")
        : url.pathname.endsWith("/about")
          ? page("about")
          : [];
    return new Response(JSON.stringify({ data }));
  });
  const data = await homeLoader();
  const html = renderToStaticMarkup(
    createElement(
      MemoryRouter,
      null,
      createElement(Home, { loaderData: data } as Parameters<typeof Home>[0]),
    ),
  );
  expect(data.services).toHaveLength(26);
  expect(html).toContain('href="/services/service-25"');
});
