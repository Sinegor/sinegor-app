import { it, expect, vi, afterEach } from "vitest";
import { readContent, withMedia } from "../app/lib/cms.server";
import type { Content } from "../app/lib/cms";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { CmsBlocks } from "../app/components/cms-blocks";

it("resolves and renders Blocks images while preserving external media and rejecting active URLs", () => {
  vi.stubEnv("CMS_ORIGIN", "http://internal:1337");
  vi.stubEnv("CMS_MEDIA_ORIGIN", "https://media.example.com");
  const content: Content = {
    slug: "blocks",
    title: "Blocks",
    sections: [
      {
        general: [
          {
            type: "image",
            image: {
              url: "/uploads/block.png",
              alternativeText: "Схема",
              mime: "image/png",
              width: 640,
              height: 480,
            },
          },
          {
            type: "image",
            image: {
              url: "https://cdn.example.com/block.png",
              alternativeText: "CDN",
              mime: "image/png",
            },
          },
          {
            type: "image",
            image: {
              url: "javascript:alert(1)",
              alternativeText: "Unsafe",
              mime: "image/png",
            },
          },
        ],
      },
    ],
  };
  const result = withMedia(content);
  const html = renderToStaticMarkup(
    createElement(CmsBlocks, { nodes: result.sections[0].general }),
  );
  expect(html).toContain('src="https://media.example.com/uploads/block.png"');
  expect(html).toContain('alt="Схема" width="640" height="480"');
  expect(html).toContain('src="https://cdn.example.com/block.png"');
  expect(html).not.toContain("javascript:");
  expect(html).not.toContain('alt="Unsafe"');
  expect(content.sections[0].general?.[0]).toMatchObject({
    image: { url: "/uploads/block.png" },
  });
});
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

it("keeps malformed CMS content as a controlled 503 after normalization", async () => {
  vi.stubEnv("CMS_ORIGIN", "http://localhost:1337");
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(
        new Response(
          JSON.stringify({ data: { slug: "home", sections: "invalid" } }),
        ),
      ),
  );
  await expect(readContent("pages", "home")).rejects.toMatchObject({
    status: 503,
  });
});

it("normalizes nested image URLs and preserves section text and settings", () => {
  vi.stubEnv("CMS_ORIGIN", "http://internal:1337");
  vi.stubEnv("CMS_MEDIA_ORIGIN", "https://media.example.com");
  const content = {
    slug: "test",
    title: "Test",
    sections: [
      {
        text: "Первый",
        image: { url: "/uploads/a.png" },
        imageLayout: { position: "left" },
      },
      { text: "Второй", image: { url: "javascript:alert(1)" } },
      { text: "Без изображения" },
    ],
  } as Content;
  const result = withMedia(content);
  expect(result.sections[0].image?.url).toBe(
    "https://media.example.com/uploads/a.png",
  );
  expect(result.sections[0].imageLayout?.position).toBe("left");
  expect(result.sections[1].image?.url).toBe("");
  expect(result.sections[2].text).toBe("Без изображения");
  expect(
    withMedia({ slug: "old", title: "Legacy" } as Content).sections,
  ).toEqual([]);
});
