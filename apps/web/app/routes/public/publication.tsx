import { Link } from "react-router";
import type { Route } from "./+types/publication";
import { publications, publicMeta } from "../../components/public-content";
export function loader({ params }: Route.LoaderArgs) {
  const article = publications.find((item) => item.slug === params.slug);
  if (!article) throw new Response("Not Found", { status: 404 });
  return { article };
}
export function meta({ data }: Route.MetaArgs) {
  return data
    ? publicMeta(data.article.title, data.article.summary)
    : [
        { title: "Публикация не найдена — SINEGOR LAB" },
        { name: "robots", content: "noindex, nofollow" },
      ];
}
export default function Publication({ loaderData }: Route.ComponentProps) {
  const { article } = loaderData;
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
