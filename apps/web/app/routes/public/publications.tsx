import type { Route } from "./+types/publications";
import { Link } from "react-router";
import { readContent, loadPublications } from "../../lib/cms.server";
import type { Content } from "../../lib/cms";
import {
  ArticleCards,
  contentMeta,
  ContentSections,
} from "../../components/cms-content";
import { publicMeta } from "../../components/public-content";
const fallbackMeta = () =>
  publicMeta(
    "Публикации",
    "Материалы SINEGOR LAB об исследовании и подготовке документов.",
  );
export const meta = ({ data }: Route.MetaArgs) =>
  data?.content ? contentMeta(data.content) : fallbackMeta();
export async function loader({ request }: Route.LoaderArgs) {
  const raw = Number(new URL(request.url).searchParams.get("offset"));
  const offset = Number.isSafeInteger(raw) && raw >= 0 ? raw : 0;
  const [list, content] = await Promise.all([
    loadPublications(offset),
    readContent("pages", "publications"),
  ]);
  return { ...list, content: (content || null) as Content | null };
}
export default function Publications({ loaderData }: Route.ComponentProps) {
  const { articles, offset, content } = loaderData;
  return (
    <section className="public-page">
      <h1>{content?.title || "Публикации"}</h1>
      {content && (
        <>
          <p>{content.summary}</p>
          <ContentSections content={content} />
        </>
      )}
      <ArticleCards articles={articles} />
      <nav aria-label="Страницы публикаций">
        {offset > 0 && (
          <Link to={`?offset=${Math.max(0, offset - 25)}`}>Назад</Link>
        )}
        {articles.length === 25 && (
          <Link to={`?offset=${offset + 25}`}>Далее</Link>
        )}
      </nav>
    </section>
  );
}
