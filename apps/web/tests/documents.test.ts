import { afterEach, expect, it, vi } from "vitest";
import { loadDocument, loadDocuments } from "../app/lib/documents.server";
import { sitemapUrls } from "../app/lib/sitemap.server";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});
const published = {
  slug: "privacy-policy",
  title: "Published document",
  publishedAt: "2026-11-02",
  revisedOn: "2026-11-01",
  body: [],
  pdf: { url: "/uploads/test.pdf", mime: "application/pdf" },
};

it("provides four placeholders without CMS and rejects unknown slugs", async () => {
  vi.stubEnv("CMS_ORIGIN", "");
  expect(await loadDocuments()).toHaveLength(4);
  expect(await loadDocument("privacy-policy")).toMatchObject({
    title: "Политика обработки персональных данных",
    content: null,
  });
  await expect(loadDocument("unknown")).rejects.toMatchObject({ status: 404 });
});

it("loads fresh published content and resolves PDF media without a rebuild", async () => {
  vi.stubEnv("CMS_ORIGIN", "http://cms.internal");
  const fetch = vi
    .fn()
    .mockResolvedValue(new Response(JSON.stringify({ data: published })));
  vi.stubGlobal("fetch", fetch);
  expect((await loadDocument("privacy-policy")).content?.pdf?.url).toBe(
    "http://cms.internal/uploads/test.pdf",
  );
  fetch.mockResolvedValue(
    new Response(
      JSON.stringify({ data: { ...published, title: "New revision" } }),
    ),
  );
  expect((await loadDocument("privacy-policy")).title).toBe("New revision");
  expect(fetch.mock.calls[0][1]).toMatchObject({ cache: "no-store" });
});

it("keeps reserved drafts pending, returns 404 for other missing documents and propagates CMS failures", async () => {
  vi.stubEnv("CMS_ORIGIN", "http://cms.internal");
  vi.stubGlobal("fetch", async () => new Response(null, { status: 404 }));
  expect((await loadDocument("service-rules")).content).toBeNull();
  await expect(loadDocument("unknown")).rejects.toMatchObject({ status: 404 });
  vi.stubGlobal("fetch", async () => new Response(null, { status: 503 }));
  await expect(loadDocument("service-rules")).rejects.toMatchObject({
    status: 503,
  });
});

it("lists published documents and excludes drafts and noindex documents from sitemap", async () => {
  vi.stubEnv("CMS_ORIGIN", "http://cms.internal");
  vi.stubGlobal(
    "fetch",
    async (input: URL) =>
      new Response(
        JSON.stringify({
          data: input.pathname.endsWith("/documents")
            ? [
                published,
                { ...published, slug: "service-rules", publishedAt: null },
                { ...published, slug: "hidden", seo: { noindex: true } },
              ]
            : [],
        }),
      ),
  );
  expect(
    (await loadDocuments()).find((item) => item.slug === "service-rules")
      ?.content,
  ).toBeNull();
  const urls = await sitemapUrls("https://public.example");
  expect(urls).toContain("https://public.example/documents");
  expect(urls).toContain("https://public.example/documents/privacy-policy");
  expect(urls).not.toContain("https://public.example/documents/service-rules");
  expect(urls).not.toContain("https://public.example/documents/hidden");
});
