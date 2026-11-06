import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { loadDocument, loadDocuments } from "../app/lib/documents.server";
import { sitemapUrls } from "../app/lib/sitemap.server";

beforeEach(() => vi.spyOn(console, "error").mockImplementation(() => {}));
afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
const published = {
  slug: "privacy-policy",
  title: "Published document",
  publishedAt: "2026-11-02",
  revisedOn: "2026-11-01",
  body: [{ type: "paragraph", children: [{ type: "text", text: "CMS body" }] }],
  pdf: { url: "/uploads/test.pdf", mime: "application/pdf" },
  seo: { title: "CMS SEO", noindex: true },
};

it("reports unavailable CMS instead of generating documents when unconfigured", async () => {
  vi.stubEnv("CMS_ORIGIN", "");
  await expect(loadDocuments()).rejects.toMatchObject({ status: 503 });
  await expect(loadDocument("privacy-policy")).rejects.toMatchObject({
    status: 503,
  });
});

it("returns 404 for missing required and arbitrary records without placeholders", async () => {
  vi.stubEnv("CMS_ORIGIN", "http://cms.internal");
  vi.stubGlobal("fetch", async () => new Response(null, { status: 404 }));
  for (const slug of [
    "privacy-policy",
    "personal-data-consent",
    "service-rules",
    "unknown",
    "provider-information",
  ])
    await expect(loadDocument(slug)).rejects.toMatchObject({ status: 404 });
  expect(console.error).toHaveBeenCalledWith(
    "Public documents configuration error: required document is not published",
    "privacy-policy",
  );
  expect(console.error).not.toHaveBeenCalledWith(expect.anything(), "unknown");
});

it("returns an empty CMS catalog and diagnoses missing required documents without restoring them", async () => {
  vi.stubEnv("CMS_ORIGIN", "http://cms.internal");
  vi.stubGlobal(
    "fetch",
    async () => new Response(JSON.stringify({ data: [] })),
  );
  expect(await loadDocuments()).toEqual([]);
  expect(console.error).toHaveBeenCalledTimes(3);
});

it("loads fresh published body, title, slug, revision, SEO and PDF without a rebuild", async () => {
  vi.stubEnv("CMS_ORIGIN", "http://cms.internal");
  const fetch = vi
    .fn()
    .mockResolvedValue(new Response(JSON.stringify({ data: published })));
  vi.stubGlobal("fetch", fetch);
  expect(await loadDocument("privacy-policy")).toMatchObject({
    slug: "privacy-policy",
    title: "Published document",
    content: {
      body: published.body,
      revisedOn: "2026-11-01",
      seo: published.seo,
      pdf: { url: "http://cms.internal/uploads/test.pdf" },
    },
  });
  fetch.mockResolvedValue(
    new Response(
      JSON.stringify({ data: { ...published, title: "New revision" } }),
    ),
  );
  expect((await loadDocument("privacy-policy")).title).toBe("New revision");
  expect(fetch.mock.calls[0][1]).toMatchObject({ cache: "no-store" });
});

it("never exposes a draft returned by an inconsistent CMS", async () => {
  vi.stubEnv("CMS_ORIGIN", "http://cms.internal");
  vi.stubGlobal(
    "fetch",
    async () =>
      new Response(
        JSON.stringify({ data: { ...published, publishedAt: null } }),
      ),
  );
  await expect(loadDocument("privacy-policy")).rejects.toMatchObject({
    status: 404,
  });
});

it("keeps network failure, server errors and malformed responses distinct from 404", async () => {
  vi.stubEnv("CMS_ORIGIN", "http://cms.internal");
  for (const fetch of [
    async () => {
      throw new TypeError("network failure");
    },
    async () => new Response(null, { status: 503 }),
    async () => new Response("invalid json"),
  ]) {
    vi.stubGlobal("fetch", fetch);
    await expect(loadDocument("service-rules")).rejects.toMatchObject({
      status: 503,
    });
    await expect(loadDocuments()).rejects.toMatchObject({ status: 503 });
  }
});

it("lists only CMS publications and excludes drafts and noindex documents from sitemap", async () => {
  vi.stubEnv("CMS_ORIGIN", "http://cms.internal");
  vi.stubGlobal(
    "fetch",
    async (input: URL) =>
      new Response(
        JSON.stringify({
          data: input.pathname.endsWith("/documents")
            ? [
                { ...published, seo: { noindex: false } },
                { ...published, slug: "service-rules", publishedAt: null },
                { ...published, slug: "new-document" },
              ]
            : [],
        }),
      ),
  );
  expect((await loadDocuments()).map(({ slug }) => slug)).toEqual([
    "privacy-policy",
    "new-document",
  ]);
  const urls = await sitemapUrls("https://public.example");
  expect(urls).toContain("https://public.example/documents/privacy-policy");
  expect(urls).not.toContain("https://public.example/documents/service-rules");
  expect(urls).not.toContain("https://public.example/documents/new-document");
});

it("reads every CMS catalog page instead of truncating to the first 25 records", async () => {
  vi.stubEnv("CMS_ORIGIN", "http://cms.internal");
  vi.stubGlobal(
    "fetch",
    async (input: URL) =>
      new Response(
        JSON.stringify({
          data:
            input.searchParams.get("offset") === "0"
              ? Array.from({ length: 25 }, (_, i) => ({
                  ...published,
                  slug: `doc-${i}`,
                }))
              : [{ ...published, slug: "last-doc" }],
        }),
      ),
  );
  const docs = await loadDocuments();
  expect(docs).toHaveLength(26);
  expect(docs.at(-1)?.slug).toBe("last-doc");
});
