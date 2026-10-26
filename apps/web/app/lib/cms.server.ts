import type { Content, ContentKind, Media } from "./cms";
import { PUBLICATION_PAGE_SIZE } from "./public-url";
export async function readContent(
  kind: ContentKind,
  slug?: string,
  offset = 0,
): Promise<Content | Content[] | null | undefined> {
  const origin = process.env.CMS_ORIGIN;
  if (!origin) return undefined;
  const url = new URL(
    `/api/public-content/${kind}${slug ? `/${encodeURIComponent(slug)}` : ""}`,
    origin,
  );
  url.searchParams.set("offset", String(offset));
  try {
    const response = await fetch(url, {
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    if (response.status === 404) return null;
    if (!response.ok) throw new Error("CMS unavailable");
    const body = await response.json();
    if (!body || !("data" in body)) throw new Error("Invalid CMS response");
    return Array.isArray(body.data)
      ? body.data.map(withMedia)
      : body.data
        ? withMedia(body.data)
        : null;
  } catch {
    throw new Response("Content temporarily unavailable", { status: 503 });
  }
}
export async function readAllContent(kind: ContentKind) {
  const items: Content[] = [];
  // The public Strapi endpoint has a fixed page size of 25.
  for (let offset = 0; ; offset += 25) {
    const page = await readContent(kind, undefined, offset);
    if (page === undefined) return undefined;
    if (!Array.isArray(page))
      throw new Response("Content temporarily unavailable", { status: 503 });
    items.push(...page);
    if (page.length < 25) return items;
    if (items.length > 50_000)
      throw new Response("Content temporarily unavailable", { status: 503 });
  }
}
export async function loadPage(kind: "pages" | "services", slug: string) {
  const result = await readContent(kind, slug);
  if (result === null) throw new Response("Not Found", { status: 404 });
  return { content: (result ?? null) as Content | null };
}
export async function loadPublications(offset = 0) {
  if (
    !Number.isSafeInteger(offset) ||
    offset < 0 ||
    offset % PUBLICATION_PAGE_SIZE !== 0
  )
    throw new Response("Not Found", { status: 404 });
  const articles = await publicationList(offset);
  if (offset > 0 && articles.length === 0)
    throw new Response("Not Found", { status: 404 });
  // A full page does not by itself prove there is another page.
  const hasNext =
    articles.length === PUBLICATION_PAGE_SIZE &&
    (await publicationList(offset + PUBLICATION_PAGE_SIZE)).length > 0;
  return { articles, offset, hasNext };
}
async function publicationList(offset: number): Promise<Content[]> {
  const data = await readContent("publications", undefined, offset);
  if (data === undefined) return [];
  if (!Array.isArray(data))
    throw new Response("Content temporarily unavailable", { status: 503 });
  return data;
}
export function mediaUrl(path: string | undefined) {
  if (!path) return undefined;
  const origin = process.env.CMS_MEDIA_ORIGIN || process.env.CMS_ORIGIN;
  if (!origin) return undefined;
  const url = new URL(path, origin);
  return ["http:", "https:"].includes(url.protocol) ? url.href : undefined;
}
export function withMedia(content: Content): Content {
  const resolveMedia = (media: Media | null | undefined) =>
    media ? { ...media, url: mediaUrl(media.url) || "" } : null;
  return {
    ...content,
    image: resolveMedia(content.image),
    video: resolveMedia(content.video),
    sections: (content.sections || []).map((section) => ({
      ...section,
      image: resolveMedia(section.image),
    })),
  };
}
