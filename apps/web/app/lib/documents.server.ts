import type { Content } from "./cms";
import { readAllContent, readContent } from "./cms.server";
import { publicDocuments } from "./documents";
import { contentPath } from "./public-url";

export type PublicDocument = {
  slug: string;
  title: string;
  content: Content | null;
};

export async function loadDocument(slug: string): Promise<PublicDocument> {
  if (!contentPath("documents", slug))
    throw new Response("Not Found", { status: 404 });
  const data = await readContent("documents", slug);
  if (data && !Array.isArray(data) && data.publishedAt)
    return { slug, title: data.title, content: data };
  const pending = publicDocuments.find((item) => item.slug === slug);
  if (!pending) throw new Response("Not Found", { status: 404 });
  return { ...pending, content: null };
}

export async function loadDocuments(): Promise<PublicDocument[]> {
  const content = ((await readAllContent("documents")) || []).filter(
    (item) => item.publishedAt && contentPath("documents", item.slug),
  );
  const documents: PublicDocument[] = publicDocuments.map((item) => {
    const published = content.find((document) => document.slug === item.slug);
    return {
      ...item,
      title: published?.title || item.title,
      content: published || null,
    };
  });
  for (const item of content)
    if (!documents.some((document) => document.slug === item.slug))
      documents.push({ slug: item.slug, title: item.title, content: item });
  return documents;
}
