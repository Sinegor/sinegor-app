export type ContentKind = "pages" | "services" | "publications" | "documents";
export type PageLinkSection =
  "home" | "ai-analysis" | "technical" | "about" | "publications" | "contacts";
export type PageLink = { to: string; title: string };
export type FooterLink = { label: string; href: string };
export type FooterData = {
  documents: FooterLink[];
  usefulLinks: FooterLink[];
};
export type Media = {
  url: string;
  alternativeText: string;
  mime: string;
  width?: number | null;
  height?: number | null;
};
export type ImageLayout = {
  position?: "top" | "left" | "right";
  size?: "small" | "medium" | "large" | "full";
  alignment?: "left" | "center" | "right";
  caption?: string | null;
};
export type ContentSection = {
  heading?: string | null;
  general?: RichTextNode[] | null;
  /** Compatibility with previously served plain-text responses. */
  text?: string | null;
  image?: Media | null;
  imageLayout?: ImageLayout | null;
};
export type RichTextNode =
  | {
      type: "text";
      text: string;
      bold?: boolean;
      italic?: boolean;
      underline?: boolean;
      strikethrough?: boolean;
      code?: boolean;
    }
  | {
      type: "paragraph" | "quote" | "code" | "list-item";
      children: RichTextNode[];
    }
  | { type: "heading"; level: 1 | 2 | 3 | 4 | 5 | 6; children: RichTextNode[] }
  | { type: "list"; format: "ordered" | "unordered"; children: RichTextNode[] }
  | { type: "link"; url: string; children: RichTextNode[] }
  | { type: "image"; image: Media; children?: RichTextNode[] };
export type Content = {
  slug: string;
  title: string;
  summary?: string | null;
  publishedAt?: string | null;
  linkSection?: PageLinkSection | null;
  linkOrder?: number | null;
  sections: ContentSection[];
  body?: RichTextNode[] | null;
  revisedOn?: string | null;
  pdf?: Media | null;
  seo?: {
    title?: string | null;
    description?: string | null;
    noindex?: boolean;
  } | null;
  image?: Media | null;
  imageLayout?: ImageLayout | null;
  video?: Media | null;
  videoCaption?: string | null;
  contactEmail?: string | null;
  contactPhone?: string | null;
};
