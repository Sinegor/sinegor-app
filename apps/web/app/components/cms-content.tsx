import { Link } from "react-router";
import type { Content } from "../lib/cms";
import { Notice } from "./ui";
export function ContentSections({ content }: { content: Content }) {
  return (
    <>
      {content.sections?.map((section, index) => (
        <section key={index}>
          {section.heading && <h2>{section.heading}</h2>}
          {section.text.split(/\n\s*\n/).map((paragraph, i) => (
            <p key={i}>{paragraph}</p>
          ))}
        </section>
      ))}
    </>
  );
}
export function ContentPage({ content }: { content: Content }) {
  return (
    <article className="public-page public-prose">
      <h1>{content.title}</h1>
      {content.summary && <p className="lead">{content.summary}</p>}
      {content.image?.url && (
        <img
          className="cms-image"
          src={content.image.url}
          alt={content.image.alternativeText || ""}
        />
      )}
      <ContentSections content={content} />
      <Link className="button-link" to="/contacts#consultation">
        Запросить консультацию
      </Link>
    </article>
  );
}
export function ArticleCards({ articles }: { articles: Content[] }) {
  return articles.length ? (
    <div className="public-grid">
      {articles.map((article) => (
        <section className="card" key={article.slug}>
          <h2>{article.title}</h2>
          {article.image?.url && (
            <img
              className="cms-image"
              src={article.image.url}
              alt={article.image.alternativeText || ""}
            />
          )}
          <p>{article.summary}</p>
          <Link to={`/publications/${encodeURIComponent(article.slug)}`}>
            Читать статью
          </Link>
        </section>
      ))}
    </div>
  ) : (
    <Notice>Опубликованных материалов пока нет.</Notice>
  );
}
export function contentMeta(content: Content) {
  return [
    { title: `${content.seo?.title || content.title} — SINEGOR LAB` },
    {
      name: "description",
      content: content.seo?.description || content.summary || content.title,
    },
  ];
}
