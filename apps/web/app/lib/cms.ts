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
  heading?: string;
  text: string;
  image?: Media | null;
  imageLayout?: ImageLayout | null;
};
export type Content = {
  slug: string;
  title: string;
  summary?: string;
  publishedAt?: string;
  sections: ContentSection[];
  seo?: { title?: string; description?: string };
  image?: Media | null;
  imageLayout?: ImageLayout | null;
  video?: Media | null;
  videoCaption?: string;
  contactEmail?: string;
  contactPhone?: string;
};
