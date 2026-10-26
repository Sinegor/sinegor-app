import type { ContentKind, PageLinkSection } from "./cms";

export const PUBLICATION_PAGE_SIZE = 25;
export const linkSections: Record<PageLinkSection, string> = {
  home: "/",
  "ai-analysis": "/services/ai-analysis",
  technical: "/services/technical",
  about: "/about",
  publications: "/publications",
  contacts: "/contacts",
};

export function linkSectionForPath(pathname: string): PageLinkSection | null {
  const path = normalizePublicPath(pathname);
  return (
    (Object.entries(linkSections).find(([, target]) => target === path)?.[0] as
      PageLinkSection | undefined) || null
  );
}

// Fixed pages share the CMS document with their /pages/:slug aliases.
const pagePaths: Record<string, string> = {
  home: "/",
  about: "/about",
  contacts: "/contacts",
  publications: "/publications",
};

export function normalizePublicPath(pathname: string): string | null {
  const path = pathname.replace(/\/+$/, "") || "/";
  let parts: string[];
  try {
    parts = path.split("/").map(decodeURIComponent);
  } catch {
    return null;
  }
  if (path === "/") return "/";
  const prefix = parts[1]?.toLowerCase();
  if (
    parts.length === 2 &&
    ["about", "contacts", "publications"].includes(prefix)
  )
    return `/${prefix}`;
  if (
    parts.length !== 3 ||
    !["pages", "services", "publications"].includes(prefix) ||
    !parts[2]
  )
    return null;
  const slug = parts[2];
  // Slugs are case sensitive: About and about can be different CMS documents.
  if (prefix === "pages" && Object.hasOwn(pagePaths, slug))
    return pagePaths[slug];
  // A literal trailing "_" collides with React Router's /_.data marker.
  const encodedSlug = slug === "_" ? "%5F" : encodeURIComponent(slug);
  return `/${prefix}/${encodedSlug}`;
}

export function publicationOffset(search: string): number {
  const offset = Number(new URLSearchParams(search).get("offset"));
  return Number.isSafeInteger(offset) && offset >= 0 ? offset : 0;
}

export function canonicalUrl(origin: string, pathname: string, search = "") {
  const path = normalizePublicPath(pathname);
  if (path === null) return null;
  const url = new URL(path, origin);
  const offset = path === "/publications" ? publicationOffset(search) : 0;
  if (offset > 0) url.searchParams.set("offset", String(offset));
  return url.href;
}

export function contentPath(kind: ContentKind, slug: string): string | null {
  // These values cannot identify an HTML document in the current router.
  if (
    !slug ||
    [".", ".."].includes(slug) ||
    /[\\/]/.test(slug) ||
    slug.endsWith(".data")
  )
    return null;
  return normalizePublicPath(`/${kind}/${encodeURIComponent(slug)}`);
}
