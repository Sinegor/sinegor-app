import type { Content } from "./cms";
import { readAllContent, readContent } from "./cms.server";
import { requiredDocumentLinks } from "./documents";
import { contentPath } from "./public-url";

export type PublicDocument = {
  slug: string;
  title: string;
  content: Content;
};

function reportMissingRequired(slug: string) {
  if (requiredDocumentLinks.some((item) => item.slug === slug))
    console.error(
      "Public documents configuration error: required document is not published",
      slug,
    );
}

export async function loadDocument(slug: string): Promise<PublicDocument> {
  if (!contentPath("documents", slug))
    throw new Response("Not Found", { status: 404 });
  const data = await readContent("documents", slug);
  if (data === undefined || Array.isArray(data))
    throw new Response("Content temporarily unavailable", { status: 503 });
  if (!data?.publishedAt) {
    reportMissingRequired(slug);
    throw new Response("Not Found", { status: 404 });
  }
  return { slug: data.slug, title: data.title, content: data };
}

export async function loadDocuments(): Promise<PublicDocument[]> {
  const data = await readAllContent("documents");
  if (data === undefined)
    throw new Response("Content temporarily unavailable", { status: 503 });
  const published = data.filter(
    (item) => item.publishedAt && contentPath("documents", item.slug),
  );
  for (const required of requiredDocumentLinks)
    if (!published.some((item) => item.slug === required.slug))
      reportMissingRequired(required.slug);
  return published.map((content) => ({
    slug: content.slug,
    title: content.title,
    content,
  }));
}
