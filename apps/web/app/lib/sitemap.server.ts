import { readAllContent } from "./cms.server";
import { canonicalUrl, contentPath, PUBLICATION_PAGE_SIZE } from "./public-url";

const standalonePaths = [
  "/",
  "/about",
  "/contacts",
  "/documents",
  "/publications",
  "/services/ai-analysis",
  "/services/technical",
];

export async function sitemapUrls(origin: string): Promise<string[]> {
  const kinds = ["pages", "services", "publications", "documents"] as const;
  const collections = await Promise.all(kinds.map(readAllContent));
  if (collections.every((items) => items === undefined))
    return standalonePaths.map((path) => canonicalUrl(origin, path)!);
  const urls = new Set<string>();
  urls.add(canonicalUrl(origin, "/documents")!);
  const add = (path: string, search = "") => {
    const url = canonicalUrl(origin, path, search);
    if (url) urls.add(url);
  };
  for (const [i, kind] of kinds.entries()) {
    for (const item of collections[i] || []) {
      if (!item.publishedAt || item.seo?.noindex) continue;
      const path = contentPath(kind, item.slug);
      if (path) add(path);
    }
  }
  const pages = collections[0] || [];
  const publications = collections[2] || [];
  // The publications index remains available even without its optional CMS page.
  const index = pages.find(
    (page) => page.slug === "publications" && page.publishedAt,
  );
  if (!index?.seo?.noindex) {
    add("/publications");
    for (
      let offset = PUBLICATION_PAGE_SIZE;
      offset < publications.length;
      offset += PUBLICATION_PAGE_SIZE
    )
      add("/publications", `?offset=${offset}`);
  }
  return [...urls].sort();
}

function escapeXml(value: string) {
  return value.replace(
    /[<>&"']/g,
    (character) =>
      ({
        "<": "&lt;",
        ">": "&gt;",
        "&": "&amp;",
        '"': "&quot;",
        "'": "&apos;",
      })[character]!,
  );
}

export function renderSitemap(urls: string[]) {
  const xml =
    '<?xml version="1.0" encoding="UTF-8"?>\n' +
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' +
    urls.map((url) => `  <url><loc>${escapeXml(url)}</loc></url>`).join("\n") +
    "\n</urlset>\n";
  if (urls.length > 50_000 || Buffer.byteLength(xml, "utf8") > 50 * 1024 * 1024)
    throw new Error("Sitemap exceeds the single-file protocol limits");
  return xml;
}
