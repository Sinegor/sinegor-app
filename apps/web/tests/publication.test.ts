import { it, expect } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router";
import Publication, { loader } from "../app/routes/public/publication";
import { publications } from "../app/components/public-content";

it("loads the requested article and renders its full text as safe SSR markup", async () => {
  const article = {
    slug: "test",
    title: "Тестовая статья",
    summary: "Описание",
    publishedAt: "2026-10-23",
    paragraphs: ["Первый абзац", "<script>untrusted</script>"],
  };
  publications.push(article);
  try {
    const data = await loader({ params: { slug: "test" } } as Parameters<
      typeof loader
    >[0]);
    const markup = renderToStaticMarkup(
      createElement(
        MemoryRouter,
        null,
        createElement(Publication, { loaderData: data } as Parameters<
          typeof Publication
        >[0]),
      ),
    );
    expect(markup).toContain("Тестовая статья");
    expect(markup).toContain("Первый абзац");
    expect(markup).toContain("&lt;script&gt;");
    expect(markup).not.toContain("<script>");
    await expect(
      loader({ params: { slug: "missing" } } as Parameters<typeof loader>[0]),
    ).rejects.toMatchObject({ status: 404 });
  } finally {
    publications.pop();
  }
});
