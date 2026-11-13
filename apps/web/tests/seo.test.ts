import { expect, it } from "vitest";
import type { MetaDescriptor } from "react-router";
import type { Content } from "../app/lib/cms";
import { meta as homeMeta } from "../app/routes/public/home";
import { meta as aboutMeta } from "../app/routes/public/about";
import { meta as publicationMeta } from "../app/routes/public/publication";
import { meta as publicationsMeta } from "../app/routes/public/publications";

const content: Content = {
  slug: "example",
  title: "Заголовок материала",
  summary: "Вводный текст",
  sections: [],
  seo: { title: "Заголовок для поиска", description: "Описание из CMS" },
  image: {
    url: "https://media.example.org/uploads/cover.jpg",
    mime: "image/jpeg",
    alternativeText: "Обложка",
  },
};

function meta(
  fn: (args: never) => MetaDescriptor[],
  data: unknown,
  pathname: string,
  route: string,
  search = "",
  error?: unknown,
) {
  return fn({
    data,
    error,
    location: { pathname, search },
    matches: [
      {
        id: "layouts/public",
        data: { publicOrigin: "https://sinegor-lab.website" },
      },
      { id: route, data },
    ],
  } as never);
}

function schemas(tags: MetaDescriptor[]) {
  return tags.flatMap((tag) =>
    "script:ld+json" in tag
      ? [tag["script:ld+json"] as Record<string, unknown>]
      : [],
  );
}

it("uses the same live CMS values for ordinary metadata and Open Graph", () => {
  const tags = meta(homeMeta, { content }, "/", "routes/public/home");
  expect(tags).toContainEqual({
    title: "Заголовок для поиска — SINEGOR LAB",
  });
  expect(tags).toContainEqual({
    property: "og:title",
    content: "Заголовок для поиска — SINEGOR LAB",
  });
  expect(tags).toContainEqual({
    property: "og:description",
    content: "Описание из CMS",
  });
  expect(tags).toContainEqual({
    property: "og:url",
    content: "https://sinegor-lab.website/",
  });
  expect(tags).toContainEqual({
    property: "og:image",
    content: "https://media.example.org/uploads/cover.jpg",
  });
  expect(tags).toContainEqual({ property: "og:type", content: "website" });
});

it("keeps real catalogue offsets and removes tracking parameters from og:url", () => {
  const tags = meta(
    publicationsMeta,
    { content, articles: [], offset: 25, hasNext: false },
    "/publications",
    "routes/public/publications",
    "?offset=25&utm_source=test",
  );
  expect(tags).toContainEqual({
    property: "og:url",
    content: "https://sinegor-lab.website/publications?offset=25",
  });
});

it("describes the actual article and navigation without inventing authors or dates", () => {
  const tags = meta(
    publicationMeta,
    { content: { ...content, publishedAt: "2026-11-01T12:00:00.000Z" } },
    "/publications/example",
    "routes/public/publication",
  );
  expect(tags).toContainEqual({ property: "og:type", content: "article" });
  const article = schemas(tags).find((item) => item["@type"] === "Article");
  expect(article).toMatchObject({
    "@context": "https://schema.org",
    headline: "Заголовок материала",
    description: "Описание из CMS",
    url: "https://sinegor-lab.website/publications/example",
    datePublished: "2026-11-01T12:00:00.000Z",
    image: "https://media.example.org/uploads/cover.jpg",
  });
  expect(article).not.toHaveProperty("author");
  expect(article).not.toHaveProperty("publisher");
  expect(article).not.toHaveProperty("dateModified");
  expect(schemas(tags)).toContainEqual({
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      {
        "@type": "ListItem",
        position: 1,
        name: "Главная",
        item: "https://sinegor-lab.website/",
      },
      {
        "@type": "ListItem",
        position: 2,
        name: "Публикации",
        item: "https://sinegor-lab.website/publications",
      },
      {
        "@type": "ListItem",
        position: 3,
        name: "Заголовок материала",
        item: "https://sinegor-lab.website/publications/example",
      },
    ],
  });
});

it("emits Person only when the about page actually identifies the attorney", () => {
  const about = {
    ...content,
    title: "О проекте",
    sections: [
      { text: "SINEGOR LAB — проект адвоката Артемьева Дмитрия Валерьевича" },
    ],
  };
  const tags = meta(
    aboutMeta,
    { content: about },
    "/about",
    "routes/public/about",
  );
  expect(schemas(tags)).toContainEqual({
    "@context": "https://schema.org",
    "@type": "Person",
    "@id": "https://sinegor-lab.website/about#person",
    name: "Артемьев Дмитрий Валерьевич",
    url: "https://sinegor-lab.website/about",
  });
  const changed = meta(aboutMeta, { content }, "/about", "routes/public/about");
  expect(schemas(changed).some((item) => item["@type"] === "Person")).toBe(
    false,
  );
});

it("uses an absolute brand image when no usable page image exists", () => {
  const tags = meta(
    homeMeta,
    {
      content: {
        ...content,
        image: { ...content.image!, url: "javascript:x" },
      },
    },
    "/",
    "routes/public/home",
  );
  const image = tags.find(
    (tag) => "property" in tag && tag.property === "og:image",
  );
  expect(image).toMatchObject({
    content: expect.stringMatching(/^https:\/\/sinegor-lab\.website\//),
  });
  expect(JSON.stringify(tags)).not.toContain("javascript:");
});

it("recognizes the visible attorney name split across formatted CMS text nodes", () => {
  const tags = meta(
    aboutMeta,
    {
      content: {
        ...content,
        sections: [
          {
            general: [
              {
                type: "paragraph",
                children: [
                  { type: "text", text: "Проект адвоката " },
                  { type: "text", text: "Артемьева ", bold: true },
                  { type: "text", text: "Дмитрия ", italic: true },
                  { type: "text", text: "Валерьевича" },
                ],
              },
            ],
          },
        ],
      },
    },
    "/about",
    "routes/public/about",
  );
  expect(schemas(tags)).toContainEqual(
    expect.objectContaining({
      "@type": "Person",
      name: "Артемьев Дмитрий Валерьевич",
    }),
  );
});

it("suppresses public metadata on errors and does not invent content for missing articles", () => {
  const tags = meta(
    publicationMeta,
    undefined,
    "/publications/missing",
    "routes/public/publication",
    "",
    new Response(null, { status: 404 }),
  );
  expect(
    tags.some(
      (tag) =>
        "property" in tag &&
        typeof tag.property === "string" &&
        tag.property.startsWith("og:"),
    ),
  ).toBe(false);
  expect(schemas(tags)).toEqual([]);
});

it("preserves noindex and emits no structured-data claim for an excluded page", () => {
  const tags = meta(
    homeMeta,
    { content: { ...content, seo: { ...content.seo, noindex: true } } },
    "/",
    "routes/public/home",
  );
  expect(tags).toContainEqual({ name: "robots", content: "noindex, follow" });
  expect(schemas(tags)).toEqual([]);
});
