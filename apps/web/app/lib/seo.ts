import type { MetaDescriptor } from "react-router";
import type { Content, RichTextNode } from "./cms";
import { canonicalUrl } from "./public-url";
import brandImage from "../../assets/AI Core and Holographic Justice.png";

type MetaArgs = {
  data: unknown;
  error?: unknown;
  location: { pathname: string; search: string };
  matches: readonly ({ id: string; data?: unknown } | undefined)[];
};

function imageUrl(value: string | undefined, origin: string) {
  if (!value) return undefined;
  try {
    const url = new URL(value, origin);
    return ["http:", "https:"].includes(url.protocol) &&
      !url.username &&
      !url.password
      ? url.href
      : undefined;
  } catch {
    return undefined;
  }
}

function blockText(nodes: RichTextNode[] | null | undefined): string {
  return (nodes || [])
    .map((node) =>
      "text" in node
        ? node.text
        : "children" in node
          ? blockText(node.children)
          : "",
    )
    .join(" ");
}

function attorneyName(content: Content | undefined) {
  // The standalone about page identifies this attorney in AboutSummary.
  if (!content) return "Артемьев Д. В.";
  const text = [
    content.title,
    content.summary,
    ...content.sections.flatMap((section) => [
      section.heading,
      section.text,
      blockText(section.general),
    ]),
  ]
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();
  // Keep the confirmed identity only while the visible CMS text supports it.
  if (
    text.includes("Артемьев Дмитрий Валерьевич") ||
    text.includes("Артемьева Дмитрия Валерьевича")
  )
    return "Артемьев Дмитрий Валерьевич";
  if (/Артемьев[а-яё]*\s+Д\.\s*В\./u.test(text)) return "Артемьев Д. В.";
  return undefined;
}

/** Add public metadata to the route's existing title/description, never replace them. */
export function withPublicMetadata(
  args: MetaArgs,
  base: MetaDescriptor[],
): MetaDescriptor[] {
  const parent = args.matches?.find((match) => match?.id === "layouts/public")
    ?.data as { publicOrigin?: string } | undefined;
  const route = args.matches?.at(-1)?.id;
  if (
    args.error ||
    args.data === undefined ||
    !parent?.publicOrigin ||
    !route?.startsWith("routes/public/")
  )
    return base;
  const url = canonicalUrl(
    parent.publicOrigin,
    args.location.pathname,
    args.location.search,
  );
  if (!url) return base;
  const titleTag = base.find((tag) => "title" in tag);
  const title = titleTag && "title" in titleTag ? titleTag.title : undefined;
  const description = base.find(
    (tag) => "name" in tag && tag.name === "description",
  );
  if (
    typeof title !== "string" ||
    !description ||
    !("content" in description) ||
    typeof description.content !== "string"
  )
    return base;

  const data = args.data as { content?: Content; article?: Content };
  const content = data.content || data.article;
  const image = imageUrl(content?.image?.url, parent.publicOrigin);
  const article = route === "routes/public/publication" && content;
  const result: MetaDescriptor[] = [
    ...base,
    { property: "og:title", content: title },
    { property: "og:description", content: description.content },
    { property: "og:url", content: url },
    {
      property: "og:image",
      content: image || imageUrl(brandImage, parent.publicOrigin)!,
    },
    { property: "og:type", content: article ? "article" : "website" },
  ];
  if (content?.seo?.noindex) return result;
  const label = content?.title || title.replace(/ — SINEGOR LAB$/, "");
  if (args.location.pathname !== "/") {
    const crumbs = [{ name: "Главная", item: new URL("/", url).href }];
    if (route === "routes/public/publication")
      crumbs.push({
        name: "Публикации",
        item: new URL("/publications", url).href,
      });
    if (route === "routes/public/document")
      crumbs.push({ name: "Документы", item: new URL("/documents", url).href });
    crumbs.push({ name: label, item: url });
    result.push({
      "script:ld+json": {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        itemListElement: crumbs.map((crumb, index) => ({
          "@type": "ListItem",
          position: index + 1,
          ...crumb,
        })),
      },
    });
  }
  if (article)
    result.push({
      "script:ld+json": {
        "@context": "https://schema.org",
        "@type": "Article",
        headline: article.title,
        description: description.content,
        url,
        ...(image ? { image } : {}),
        ...(article.publishedAt &&
        /^\d{4}-\d{2}-\d{2}(?:T|$)/.test(article.publishedAt) &&
        Number.isFinite(Date.parse(article.publishedAt))
          ? { datePublished: article.publishedAt }
          : {}),
      },
    });
  if (route === "routes/public/about") {
    const name = attorneyName(content);
    if (name)
      result.push({
        "script:ld+json": {
          "@context": "https://schema.org",
          "@type": "Person",
          "@id": `${url}#person`,
          name,
          url,
        },
      });
  }
  return result;
}
