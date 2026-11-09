import { afterEach, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter, type ShouldRevalidateFunctionArgs } from "react-router";
import { PublicFooter } from "../app/components/public-footer";
import { readFooter } from "../app/lib/cms.server";
import { loader, shouldRevalidate } from "../app/layouts/public";
import type { FooterData } from "../app/lib/cms";

const empty = { documents: [], usefulLinks: [] };
const links = (count: number) =>
  Array.from({ length: count }, (_, i) => ({
    label: `Документ ${i} <script>unsafe()</script>`,
    href: `/documents/test-${i}`,
  }));
const html = (data: FooterData) =>
  renderToStaticMarkup(
    <MemoryRouter>
      <PublicFooter year={2026} data={data} />
    </MemoryRouter>,
  );
const reply = (data: unknown) => new Response(JSON.stringify({ data }));

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

it("renders CMS order, labels and all 50 links per section in SSR with independent native disclosure", () => {
  const markup = html({
    documents: links(50),
    usefulLinks: links(50).reverse(),
  });
  expect(markup).toContain(">Документы</h2>");
  expect(markup).toContain(">Полезные ссылки</h2>");
  expect(markup.match(/<a /g)).toHaveLength(100);
  expect(markup.match(/<details[ >]/g)).toHaveLength(2);
  expect(markup).not.toContain("<details open");
  expect(markup.match(/Показать все/g)).toHaveLength(2);
  expect(markup.match(/Свернуть/g)).toHaveLength(2);
  expect(markup).toContain("&lt;script&gt;unsafe()&lt;/script&gt;");
  expect(markup).not.toContain("<script>");
  const documents = markup.split("Полезные ссылки")[0];
  expect(documents.indexOf('href="/documents/test-0"')).toBeLessThan(
    documents.indexOf('href="/documents/test-49"'),
  );
  const useful = markup.split("Полезные ссылки")[1];
  expect(useful.indexOf('href="/documents/test-49"')).toBeLessThan(
    useful.indexOf('href="/documents/test-0"'),
  );
});

it.each([0, 1, 5])(
  "keeps %i links compact without a disclosure or fixed fallback links",
  (count) => {
    const markup = html({ documents: links(count), usefulLinks: [] });
    expect(markup.match(/<a /g) || []).toHaveLength(count);
    expect(markup).not.toContain("<details");
    expect(markup).not.toContain("privacy-policy");
    expect(markup).not.toContain('href="/about"');
    expect(markup).toContain("© 2026 SINEGOR LAB");
    expect(markup).toContain("IT-лаборатория адвоката Артемьева Д. В.");
  },
);

it("starts disclosure after the fifth link, independently for six and five links", () => {
  const markup = html({ documents: links(6), usefulLinks: links(5) });
  expect(markup.match(/<details[ >]/g)).toHaveLength(1);
  expect(markup.indexOf('href="/documents/test-4"')).toBeLessThan(
    markup.indexOf("<details"),
  );
  expect(markup.indexOf('href="/documents/test-5"')).toBeGreaterThan(
    markup.indexOf("<summary"),
  );
});

it("reads the current CMS footer on each server call without credentials, cache or per-link requests", async () => {
  vi.stubEnv("CMS_ORIGIN", "http://cms.test:1337");
  const first = {
    documents: links(50),
    usefulLinks: [{ label: "Внешний ресурс", href: "https://example.org/" }],
  };
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(reply(first))
    .mockResolvedValueOnce(reply(empty));
  vi.stubGlobal("fetch", fetcher);
  expect(await readFooter()).toEqual(first);
  expect(await readFooter()).toEqual(empty);
  expect(fetcher).toHaveBeenCalledTimes(2);
  for (const [url, options] of fetcher.mock.calls) {
    expect(url.pathname).toBe("/api/public-content/footer");
    expect(options.cache).toBe("no-store");
    expect(options.signal).toBeInstanceOf(AbortSignal);
    expect(options.headers).toBeUndefined();
    expect(options.credentials).toBeUndefined();
  }
});

it("uses empty lists without fetching when CMS is unconfigured", async () => {
  vi.stubEnv("CMS_ORIGIN", "");
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  expect(await readFooter()).toEqual(empty);
  expect(fetcher).not.toHaveBeenCalled();
});

it.each([null, {}, { documents: "wrong", usefulLinks: [] }])(
  "handles absent or malformed footer data without throwing: %j",
  async (data) => {
    vi.stubEnv("CMS_ORIGIN", "http://cms.test:1337");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(data)));
    expect(await readFooter()).toEqual(empty);
  },
);

it("keeps footer failure local for network, timeout, invalid origin, HTTP and malformed JSON errors", async () => {
  vi.stubEnv("CMS_ORIGIN", "http://cms.test:1337");
  for (const response of [
    new Error("offline"),
    new DOMException("timeout", "TimeoutError"),
    new Response(null, { status: 503 }),
    new Response(null, { status: 404 }),
    new Response("not json"),
  ]) {
    vi.stubGlobal(
      "fetch",
      response instanceof Error
        ? vi.fn().mockRejectedValue(response)
        : vi.fn().mockResolvedValue(response),
    );
    expect(await readFooter()).toEqual(empty);
  }
  vi.stubEnv("CMS_ORIGIN", "invalid origin");
  expect(await readFooter()).toEqual(empty);
});

it("projects only label/href, filters invalid links and preserves safe relative and HTTP(S) links", async () => {
  vi.stubEnv("CMS_ORIGIN", "http://cms.test:1337");
  const safe = [
    "/about",
    "/documents/a?x=1#part",
    "https://example.org/a",
    "http://example.org/a",
  ];
  const unsafe = [
    "javascript:alert(1)",
    "data:text/html,abc",
    "//evil.test",
    "/\\evil.test",
    "https://example.org/\npath",
    "https://example.org/a b",
    "mailto:x@example.org",
    "relative",
    "https://",
    "https://example.org/\u0085",
  ];
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      reply({
        documents: [
          ...[...safe, ...unsafe].map((href) => ({
            label: "Ссылка",
            href,
            secret: "hidden",
          })),
          null,
          { label: "", href: "/about" },
          { label: 123, href: "/about" },
        ],
        usefulLinks: [],
        secret: "hidden",
      }),
    ),
  );
  expect(await readFooter()).toEqual({
    documents: safe.map((href) => ({ label: "Ссылка", href })),
    usefulLinks: [],
  });
});

it("loads footer once in the shared SSR layout even when its CMS endpoint fails", async () => {
  vi.stubEnv("CMS_ORIGIN", "http://cms.test:1337");
  const fetcher = vi.fn(async (url: URL) => {
    if (url.pathname.endsWith("/footer"))
      return new Response(null, { status: 503 });
    return reply([]);
  });
  vi.stubGlobal("fetch", fetcher);
  const data = await loader({
    request: new Request("http://localhost/about"),
  } as Parameters<typeof loader>[0]);
  expect(data).toMatchObject({ footer: empty, pageLinks: [] });
  expect(
    fetcher.mock.calls.filter(([url]) => url.pathname.endsWith("/footer")),
  ).toHaveLength(1);
});

it.each([
  ["/documents", "/documents/one"],
  ["/documents/one", "/documents/two"],
  ["/pages/one", "/pages/two"],
  ["/", "/about"],
])(
  "revalidates the shared SSR footer when navigating %s → %s",
  (current, next) => {
    expect(
      shouldRevalidate({
        currentUrl: new URL(current, "https://example.org"),
        nextUrl: new URL(next, "https://example.org"),
        defaultShouldRevalidate: false,
      } as ShouldRevalidateFunctionArgs),
    ).toBe(true);
  },
);
