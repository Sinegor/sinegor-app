import { afterEach, expect, it, vi } from "vitest";
import { loadPublications } from "../app/lib/cms.server";
import { publicRedirect } from "../app/lib/public-url.server";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

function catalog(count: number) {
  vi.stubEnv("CMS_ORIGIN", "http://cms.internal");
  const articles = Array.from({ length: count }, (_, i) => ({
    slug: `article-${i}`,
    title: `Article ${i}`,
    sections: [],
  }));
  vi.stubGlobal("fetch", async (input: URL) => {
    const offset = Number(new URL(input).searchParams.get("offset"));
    return new Response(
      JSON.stringify({ data: articles.slice(offset, offset + 25) }),
    );
  });
}

it.each([25, 50, 1000000])(
  "returns 404 for an empty catalogue page at offset %s",
  async (offset) => {
    catalog(0);
    await expect(loadPublications(offset)).rejects.toMatchObject({
      status: 404,
    });
  },
);

it.each([-25, 1, 24, 26, 999999, 1.2, Number.MAX_SAFE_INTEGER + 1])(
  "rejects values outside the catalogue page boundaries: %s",
  async (offset) => {
    catalog(100);
    await expect(loadPublications(offset)).rejects.toMatchObject({
      status: 404,
    });
  },
);

it("keeps an empty first page available without a next link", async () => {
  catalog(0);
  expect(await loadPublications()).toEqual({
    articles: [],
    offset: 0,
    hasNext: false,
  });
});

it("does not offer a nonexistent page after exactly 25 or 50 articles", async () => {
  catalog(25);
  expect(await loadPublications()).toMatchObject({ offset: 0, hasNext: false });
  await expect(loadPublications(25)).rejects.toMatchObject({ status: 404 });
  catalog(50);
  expect(await loadPublications()).toMatchObject({ hasNext: true });
  expect(await loadPublications(25)).toMatchObject({
    offset: 25,
    hasNext: false,
  });
  await expect(loadPublications(50)).rejects.toMatchObject({ status: 404 });
});

it("keeps the distinct articles and next/previous offsets of real pages", async () => {
  catalog(51);
  const first = await loadPublications();
  const second = await loadPublications(25);
  const last = await loadPublications(50);
  expect(first).toMatchObject({ offset: 0, hasNext: true });
  expect(first.articles).toHaveLength(25);
  expect(second).toMatchObject({ offset: 25, hasNext: true });
  expect(second.articles[0].slug).toBe("article-25");
  expect(second.articles).toHaveLength(25);
  expect(last).toMatchObject({ offset: 50, hasNext: false });
  expect(last.articles.map((article) => article.slug)).toEqual(["article-50"]);
});

it.each([null, { slug: "unexpected-single-document" }])(
  "keeps invalid CMS list responses distinct from an empty catalogue",
  async (data) => {
    vi.stubEnv("CMS_ORIGIN", "http://cms.internal");
    vi.stubGlobal("fetch", async () => new Response(JSON.stringify({ data })));
    await expect(loadPublications()).rejects.toMatchObject({ status: 503 });
  },
);

it("keeps CMS failures as 503 rather than reporting a nonexistent page", async () => {
  vi.stubEnv("CMS_ORIGIN", "http://cms.internal");
  vi.stubGlobal("fetch", async () => new Response(null, { status: 503 }));
  await expect(loadPublications(25)).rejects.toMatchObject({ status: 503 });
});

it.each([
  ["?offset=0", ""],
  ["?offset=-25", ""],
  ["?offset=bad", ""],
  ["?offset=1.2", ""],
  ["?offset=Infinity", ""],
  ["?offset=9007199254740992", ""],
  ["?offset=00025", "?offset=25"],
  ["?offset=25.0", "?offset=25"],
  ["?offset=25&offset=50", "?offset=25"],
  ["?offset=25&utm_source=test&unused=1", "?offset=25"],
  ["?unused=1", ""],
])(
  "normalizes the equivalent catalogue query %s via 308",
  (search, canonicalSearch) => {
    vi.stubEnv("PUBLIC_ORIGIN", "https://public.example");
    const response = publicRedirect(
      new Request(`http://ssr.internal/publications${search}`),
    );
    expect(response?.status).toBe(308);
    expect(response?.headers.get("Location")).toBe(
      `https://public.example/publications${canonicalSearch}`,
    );
  },
);
