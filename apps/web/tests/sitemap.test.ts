import { afterEach, describe, expect, it, vi } from "vitest";
import { renderSitemap, sitemapUrls } from "../app/lib/sitemap.server";
import { loader as sitemap } from "../app/routes/resources/sitemap";
import { loader as robots } from "../app/routes/resources/robots";
import { contentMeta } from "../app/components/cms-content";
import type { Content } from "../app/lib/cms";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("dynamic public sitemap", () => {
  it("reads every CMS list page before excluding drafts and noindex documents", async () => {
    vi.stubEnv("CMS_ORIGIN", "http://cms.internal");
    const hidden = Array.from({ length: 25 }, (_, i) => ({
      slug: `hidden-${i}`,
      title: "Hidden",
      publishedAt: "2026-10-26T00:00:00Z",
      seo: { noindex: true },
    }));
    vi.stubGlobal("fetch", async (input: URL) => {
      const url = new URL(input);
      const kind = url.pathname.split("/").at(-1);
      const offset = Number(url.searchParams.get("offset"));
      const data =
        kind === "pages"
          ? [
              { slug: "about", publishedAt: "2026-10-26" },
              { slug: "draft", publishedAt: null },
            ]
          : offset === 0
            ? hidden
            : [
                { slug: "Case", publishedAt: "2026-10-26" },
                { slug: "case", publishedAt: "2026-10-26" },
              ];
      return new Response(JSON.stringify({ data }));
    });
    expect(await sitemapUrls("https://public.example")).toEqual([
      "https://public.example/about",
      "https://public.example/publications",
      "https://public.example/publications/Case",
      "https://public.example/publications/case",
      "https://public.example/publications?offset=25",
      "https://public.example/services/Case",
      "https://public.example/services/case",
    ]);
  });

  it("deduplicates aliases and omits unrouteable CMS slugs", async () => {
    vi.stubEnv("CMS_ORIGIN", "http://cms.internal");
    vi.stubGlobal(
      "fetch",
      async (input: URL) =>
        new Response(
          JSON.stringify({
            data: new URL(input).pathname.endsWith("/pages")
              ? [
                  "home",
                  "about",
                  "about",
                  "publications",
                  ".",
                  "..",
                  "invalid.data",
                  "a/b",
                ].map((slug) => ({ slug, publishedAt: "2026-10-26" }))
              : [],
          }),
        ),
    );
    expect(await sitemapUrls("https://public.example")).toEqual([
      "https://public.example/",
      "https://public.example/about",
      "https://public.example/publications",
    ]);
  });

  it("excludes a noindex publications index and all its pagination URLs", async () => {
    vi.stubEnv("CMS_ORIGIN", "http://cms.internal");
    vi.stubGlobal(
      "fetch",
      async (input: URL) =>
        new Response(
          JSON.stringify({
            data: new URL(input).pathname.endsWith("/pages")
              ? [
                  {
                    slug: "publications",
                    publishedAt: "2026-10-26",
                    seo: { noindex: true },
                  },
                ]
              : [],
          }),
        ),
    );
    expect(await sitemapUrls("https://public.example")).toEqual([]);
  });

  it("fails with a non-cacheable 503 instead of serving an incomplete sitemap", async () => {
    vi.stubEnv("CMS_ORIGIN", "http://cms.internal");
    vi.stubGlobal("fetch", async () => new Response(null, { status: 404 }));
    const response = await sitemap({
      request: new Request("https://public.example/sitemap.xml"),
    } as Parameters<typeof sitemap>[0]);
    expect(response.status).toBe(503);
    expect(response.headers.get("Cache-Control")).toBe("no-store");
    expect(await response.text()).not.toContain("<urlset");
  });

  it("escapes XML values and refuses more than 50000 entries", () => {
    expect(
      renderSitemap(['https://public.example/pages/a?one=1&two="2"\'<>']),
    ).toContain(
      "<loc>https://public.example/pages/a?one=1&amp;two=&quot;2&quot;&apos;&lt;&gt;</loc>",
    );
    expect(() =>
      renderSitemap(Array(50_001).fill("https://public.example/about")),
    ).toThrow();
  });

  it("emits an SSR noindex directive from the same SEO value used by the sitemap", () => {
    const content: Content = {
      slug: "hidden",
      title: "Hidden",
      sections: [],
      seo: { noindex: true },
    };
    expect(contentMeta(content)).toContainEqual({
      name: "robots",
      content: "noindex, follow",
    });
    expect(contentMeta({ ...content, seo: undefined })).not.toContainEqual({
      name: "robots",
      content: "noindex, follow",
    });
  });

  it("uses the runtime public origin in robots even when CMS is unavailable", async () => {
    vi.stubEnv("PUBLIC_ORIGIN", "https://public.example");
    vi.stubEnv("CMS_ORIGIN", "http://unavailable.internal");
    const response = robots({
      request: new Request("http://ssr.internal:3000/robots.txt"),
    } as Parameters<typeof robots>[0]);
    expect(response.status).toBe(200);
    expect(await response.text()).toContain(
      "Sitemap: https://public.example/sitemap.xml\n",
    );
  });
});
