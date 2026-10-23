export type Content = {
  slug: string;
  title: string;
  summary?: string;
  publishedAt?: string;
  sections: { heading?: string; text: string }[];
  seo?: { title?: string; description?: string };
  image?: { url: string; alternativeText: string; mime: string } | null;
  video?: { url: string; alternativeText: string; mime: string } | null;
  videoCaption?: string;
  contactEmail?: string;
  contactPhone?: string;
};
