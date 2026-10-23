import { it, expect, vi, afterEach } from "vitest";
import { readContent } from "../app/lib/cms.server";
afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});
it("fetches live public content without credentials or caching", async () => {
  vi.stubEnv("CMS_ORIGIN", "http://localhost:1337");
  const fetcher = vi
    .fn()
    .mockResolvedValue(
      new Response(JSON.stringify({ data: { title: "Новый текст" } })),
    );
  vi.stubGlobal("fetch", fetcher);
  expect(await readContent("pages", "home")).toMatchObject({
    title: "Новый текст",
  });
  expect(fetcher.mock.calls[0][0].toString()).toContain(
    "/api/public-content/pages/home",
  );
  expect(fetcher.mock.calls[0][1].cache).toBe("no-store");
});
it("distinguishes missing content from CMS unavailability", async () => {
  vi.stubEnv("CMS_ORIGIN", "http://localhost:1337");
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response(null, { status: 404 })),
  );
  expect(await readContent("pages", "missing")).toBeNull();
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
  await expect(readContent("pages", "home")).rejects.toMatchObject({
    status: 503,
  });
});

it("does not permit active script URLs in CMS media", async () => {
  const { mediaUrl } = await import("../app/lib/cms.server");
  vi.stubEnv("CMS_ORIGIN", "http://localhost:1337");
  expect(mediaUrl("javascript:alert(1)")).toBeUndefined();
  expect(mediaUrl("/uploads/poster.jpg")).toBe(
    "http://localhost:1337/uploads/poster.jpg",
  );
});
