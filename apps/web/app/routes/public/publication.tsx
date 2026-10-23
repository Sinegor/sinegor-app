import { readContent } from "../../lib/cms.server";
import type { Content } from "../../lib/cms";
import { ContentSections, contentMeta } from "../../components/cms-content";
import { Link } from "react-router";
import type { Route } from "./+types/publication";
import { publications, publicMeta } from "../../components/public-content";
export async function loader({ params }: Route.LoaderArgs) {
  const content = await readContent("publications", params.slug);
  if (content === null) throw new Response("Not Found", { status: 404 });
  if (content) return { article: null, content: content as Content };
  const article = publications.find((item) => item.slug === params.slug);
  if (!article) throw new Response("Not Found", { status: 404 });
  return { article, content: null };
}
export function meta({ data }: Route.MetaArgs) {
  return data?.content
    ? contentMeta(data.content)
    : data?.article
      ? publicMeta(data.article.title, data.article.summary)
      : [
          { title: "Публикация не найдена — SINEGOR LAB" },
          { name: "robots", content: "noindex, nofollow" },
        ];
}
export default function Publication({ loaderData }: Route.ComponentProps) {
  const { article, content } = loaderData;
  if (content)
    return (
      <article className="public-page public-prose">
        <Link to="/publications">Все публикации</Link>
        <h1>{content.title}</h1>
        {content.publishedAt && (
          <time dateTime={content.publishedAt}>
            {content.publishedAt.slice(0, 10)}
          </time>
        )}
        {content.image?.url && (
          <img
            className="cms-image"
            src={content.image.url}
            alt={content.image.alternativeText || ""}
          />
        )}
        <ContentSections content={content} />
      </article>
    );
  if (!article) return null;
  return (
    <article className="public-page public-prose">
      <Link to="/publications">Все публикации</Link>
      <h1>{article.title}</h1>
      <time dateTime={article.publishedAt}>
        {new Intl.DateTimeFormat("ru-RU", {
          dateStyle: "long",
          timeZone: "UTC",
        }).format(new Date(article.publishedAt))}
      </time>
      {article.paragraphs.map((paragraph, index) => (
        <p key={index}>{paragraph}</p>
      ))}
    </article>
  );
}
