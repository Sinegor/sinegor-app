import type { Content, PageLink, PageLinkSection } from "./cms";
import { readAllContent } from "./cms.server";
import { contentPath, linkSections } from "./public-url";

export function buildPageLinks(
  section: PageLinkSection,
  pages: Content[],
  services: Content[],
): PageLink[] {
  const available = new Set<string>(["/publications"]);
  for (const [kind, items] of [
    ["pages", pages],
    ["services", services],
  ] as const)
    for (const item of items) {
      if (!item.publishedAt) continue;
      const path = contentPath(kind, item.slug);
      if (path) available.add(path);
    }
  const core = new Set(Object.values(linkSections));
  const links = new Map<string, { to: string; title: string; order: number }>();
  for (const page of pages) {
    if (!page.publishedAt || page.seo?.noindex) continue;
    const to = contentPath("pages", page.slug);
    if (!to || core.has(to)) continue;
    const chosen =
      page.linkSection && Object.hasOwn(linkSections, page.linkSection)
        ? page.linkSection
        : "publications";
    const placement = available.has(linkSections[chosen])
      ? chosen
      : "publications";
    if (placement !== section) continue;
    links.set(to, {
      to,
      title: page.title,
      order:
        Number.isSafeInteger(page.linkOrder) && page.linkOrder! >= 0
          ? page.linkOrder!
          : 0,
    });
  }
  return [...links.values()]
    .sort(
      (a, b) =>
        a.order - b.order ||
        a.title.localeCompare(b.title, "ru") ||
        a.to.localeCompare(b.to),
    )
    .map(({ to, title }) => ({ to, title }));
}

export async function loadPageLinks(
  section: PageLinkSection,
): Promise<PageLink[]> {
  const [pages, services] = await Promise.all([
    readAllContent("pages"),
    readAllContent("services"),
  ]);
  return buildPageLinks(section, pages || [], services || []);
}
