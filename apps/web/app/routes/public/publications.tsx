import { withPublicMetadata } from "../../lib/seo";
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
import { ContentMedia } from "../../components/content-media";
import { publicationOffset, PUBLICATION_PAGE_SIZE } from "../../lib/public-url";
const fallbackMeta = () =>
  publicMeta(
    "Публикации",
    "Материалы SINEGOR LAB об исследовании и подготовке документов.",
  );
const pageMeta = ({ data }: Route.MetaArgs) =>
  data?.content ? contentMeta(data.content) : fallbackMeta();
export async function loader({ request }: Route.LoaderArgs) {
  const offset = publicationOffset(new URL(request.url).search);
  const [list, content] = await Promise.all([
    loadPublications(offset),
    readContent("pages", "publications"),
  ]);
  return { ...list, content: (content || null) as Content | null };
}
export const meta = (args: Route.MetaArgs) =>
  withPublicMetadata(args, pageMeta(args));

export default function Publications({ loaderData }: Route.ComponentProps) {
  const { articles, offset, content, hasNext } = loaderData;
  return (
    <section className="public-page">
      <h1>{content?.title || "Публикации"}</h1>
      {content && (
        <ContentMedia image={content.image} layout={content.imageLayout}>
          <p>{content.summary}</p>
          <ContentSections content={content} />
        </ContentMedia>
      )}
      <ArticleCards articles={articles} />
      <nav aria-label="Страницы публикаций">
        {offset > 0 && (
          <Link
            to={
              offset <= PUBLICATION_PAGE_SIZE
                ? "/publications"
                : `?offset=${offset - PUBLICATION_PAGE_SIZE}`
            }
          >
            Назад
          </Link>
        )}
        {hasNext && (
          <Link to={`?offset=${offset + PUBLICATION_PAGE_SIZE}`}>Далее</Link>
        )}
      </nav>
    </section>
  );
}
