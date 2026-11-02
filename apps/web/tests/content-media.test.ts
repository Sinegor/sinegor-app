import { expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router";
import {
  ContentPage,
  ContentSections,
  ArticleCards,
} from "../app/components/cms-content";
import type { Content } from "../app/lib/cms";
import { CmsBlocks } from "../app/components/cms-blocks";

it("preserves soft breaks, marks, nested lists and safe links without executing CMS markup", () => {
  const html = render(
    createElement(CmsBlocks, {
      nodes: [
        {
          type: "paragraph",
          children: [
            {
              type: "text",
              text: "Строка\nВторая",
              underline: true,
              strikethrough: true,
              code: true,
            },
          ],
        },
        {
          type: "link",
          url: "javascript:alert(1)",
          children: [{ type: "text", text: "Опасная ссылка" }],
        },
        {
          type: "link",
          url: "mailto:info@example.com",
          children: [{ type: "text", text: "Почта" }],
        },
        {
          type: "list",
          format: "unordered",
          children: [
            {
              type: "list-item",
              children: [
                { type: "text", text: "Внешний" },
                {
                  type: "list",
                  format: "ordered",
                  children: [
                    {
                      type: "list-item",
                      children: [{ type: "text", text: "Вложенный" }],
                    },
                  ],
                },
              ],
            },
          ],
        },
      ],
    }),
  );
  expect(html).toContain("<s><u><code>Строка<br/>Вторая</code></u></s>");
  expect(html).toContain("Опасная ссылка");
  expect(html).not.toContain("javascript:");
  expect(html).toContain('href="mailto:info@example.com"');
  expect(html).toContain(
    "<ul><li>Внешний<ol><li>Вложенный</li></ol></li></ul>",
  );
});

it("renders the nested-list structure produced by Strapi indentation as valid lists", () => {
  const html = render(
    createElement(CmsBlocks, {
      nodes: [
        {
          type: "list",
          format: "unordered",
          children: [
            {
              type: "list-item",
              children: [{ type: "text", text: "Родитель" }],
            },
            {
              type: "list",
              format: "ordered",
              children: [
                {
                  type: "list-item",
                  children: [{ type: "text", text: "Потомок" }],
                },
              ],
            },
          ],
        },
      ],
    }),
  );
  expect(html).toBe("<ul><li>Родитель<ol><li>Потомок</li></ol></li></ul>");
});

const content = {
  slug: "test",
  title: "Материал",
  summary: "Вводный текст",
  image: {
    url: "https://cms.example/image.png",
    alternativeText: 'Схема "дела"',
    mime: "image/png",
    width: 1200,
    height: 800,
  },
  imageLayout: {
    position: "right",
    size: "small",
    alignment: "left",
    caption: "Подпись <script>unsafe()</script>",
  },
  sections: [
    {
      heading: "Раздел",
      text: "Абзац один\n\nАбзац два",
      image: {
        url: "https://cms.example/section.png",
        alternativeText: "",
        mime: "image/png",
      },
      imageLayout: { position: "left", size: "large", alignment: "center" },
    },
  ],
} as Content;

function render(element: ReturnType<typeof createElement>) {
  return renderToStaticMarkup(createElement(MemoryRouter, null, element));
}

it("renders current Blocks and absent optional content in server HTML", () => {
  const current = {
    ...content,
    sections: [
      {
        general: [
          {
            type: "heading",
            level: 3,
            children: [{ type: "text", text: "Заголовок" }],
          },
          {
            type: "paragraph",
            children: [
              { type: "text", text: "Жирный", bold: true },
              { type: "text", text: "Курсив", italic: true },
              {
                type: "link",
                url: "/about",
                children: [{ type: "text", text: "Ссылка" }],
              },
            ],
          },
          {
            type: "list",
            format: "ordered",
            children: [
              {
                type: "list-item",
                children: [{ type: "text", text: "Пункт" }],
              },
            ],
          },
          { type: "quote", children: [{ type: "text", text: "Цитата" }] },
          {
            type: "code",
            children: [{ type: "text", text: "<script>test</script>" }],
          },
        ],
      },
      { general: null },
      {},
    ],
  } as unknown as Content;
  const html = render(createElement(ContentSections, { content: current }));
  expect(html).toContain("<h3>Заголовок</h3>");
  expect(html).toContain("<strong>Жирный</strong>");
  expect(html).toContain("<em>Курсив</em>");
  expect(html).toContain('<a href="/about">Ссылка</a>');
  expect(html).toContain("<ol><li>Пункт</li></ol>");
  expect(html).toContain("<blockquote>Цитата</blockquote>");
  expect(html).toContain(
    "<pre><code>&lt;script&gt;test&lt;/script&gt;</code></pre>",
  );
});

it("renders root and section illustrations with their own layouts and safe captions", () => {
  const html = render(createElement(ContentPage, { content }));
  expect(html).toContain("content-media--right");
  expect(html).toContain("content-media--small");
  expect(html).toContain("content-media--left");
  expect(html).toContain("content-media--large");
  expect(html).toContain('width="1200" height="800"');
  expect(html).toContain('alt="Схема &quot;дела&quot;"');
  expect(html).toContain(
    "<figcaption>Подпись &lt;script&gt;unsafe()&lt;/script&gt;</figcaption>",
  );
  expect(html).not.toContain("<script>");
  expect(html).toContain("Вводный текст");
  expect(html).toContain("Абзац один");
  expect(html).toContain("Абзац два");
  expect(html).toContain('href="/contacts#consultation"');
});

it("uses the same illustration layout for article cards", () => {
  const html = render(createElement(ArticleCards, { articles: [content] }));
  expect(html).toContain("content-media--right");
  expect(html).toContain(content.image!.url);
  expect(html).toContain("<h2>Материал</h2>");
  expect(html).toContain('href="/publications/test"');
});

it("keeps legacy sections without image slots and defaults an unconfigured cover", () => {
  const legacy = {
    ...content,
    imageLayout: null,
    sections: [{ text: "Старый текст" }],
  };
  const sections = render(createElement(ContentSections, { content: legacy }));
  expect(sections).toBe("<section><p>Старый текст</p></section>");
  const html = render(createElement(ContentPage, { content: legacy }));
  expect(html).toContain("content-media--top");
  expect(html).toContain("content-media--medium");
  expect(html).toContain("content-media--align-center");
});

it("rejects invalid presentation values even when received outside the CMS serializer", () => {
  const invalid = {
    ...content,
    imageLayout: {
      position: "fixed injected",
      size: "__proto__",
      alignment: "invalid",
    },
  } as unknown as Content;
  const html = render(createElement(ContentPage, { content: invalid }));
  expect(html).toContain("content-media--top");
  expect(html).toContain("content-media--medium");
  expect(html).toContain("content-media--align-center");
  expect(html).not.toContain("injected");
});
