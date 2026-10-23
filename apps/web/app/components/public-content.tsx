import { Link } from "react-router";
import { Card, Notice } from "./ui";
export function Services() {
  return (
    <section aria-labelledby="services-title">
      <p className="eyebrow">Направления работы</p>
      <h2 id="services-title">Две услуги — под вашу задачу</h2>
      <div className="public-grid">
        <Card title="ИИ-анализ документов">
          <p>
            Исследование юридических материалов: поиск сведений, сопоставление
            фактов, связи и хронология событий.
          </p>
          <Link to="/services/ai-analysis">Подробнее об исследовании</Link>
        </Card>
        <Card title="Техническая обработка">
          <p>
            Подготовка цифровых документов для последующей работы: PDF,
            текстовый слой и упорядочивание файлов.
          </p>
          <Link to="/services/technical">Подробнее об обработке</Link>
        </Card>
      </div>
    </section>
  );
}
export function PublicationsPreview() {
  return publications.length ? (
    <div className="public-grid">
      {publications.map((article) => (
        <Card key={article.slug} title={article.title}>
          <p>{article.summary}</p>
          <Link to={`/publications/${encodeURIComponent(article.slug)}`}>
            Читать статью
          </Link>
        </Card>
      ))}
    </div>
  ) : (
    <Notice>Опубликованных материалов пока нет.</Notice>
  );
}
export function AboutSummary() {
  return (
    <>
      <p>
        IT-лаборатория адвоката Артемьева Д. В. Исследование юридических
        материалов с применением технологий искусственного интеллекта и
        техническая подготовка цифровых документов.
      </p>
      <p>
        Содержание поручения, формат результата и условия работы определяются на
        предварительной консультации и закрепляются в соглашении.
      </p>
    </>
  );
}
export function publicMeta(title: string, description: string) {
  return [
    { title: `${title} — SINEGOR LAB` },
    { name: "description", content: description },
  ];
}

// Empty until approved materials are available; Strapi becomes the source in F5.
export type Publication = {
  slug: string;
  title: string;
  summary: string;
  publishedAt: string;
  paragraphs: string[];
};
export const publications: Publication[] = [];
