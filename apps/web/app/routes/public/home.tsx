import type { Route } from "./+types/home";
import type { Content } from "../../lib/cms";
import { loadPage, readContent, readAllContent } from "../../lib/cms.server";
import { contentPath } from "../../lib/public-url";
import {
  ContentSections,
  ArticleCards,
  contentMeta,
} from "../../components/cms-content";
export async function loader() {
  const { content } = await loadPage("pages", "home");
  if (!content)
    return { content: null, services: [], articles: [], about: null };
  const [services, articles, about] = await Promise.all([
    readAllContent("services"),
    readContent("publications"),
    readContent("pages", "about"),
  ]);
  return {
    content,
    services: (services || []) as Content[],
    articles: ((articles || []) as Content[]).slice(0, 3),
    about: about as Content | null,
  };
}
import { Link } from "react-router";
import { LabArt } from "../../components/lab-art";
import { VideoPresentation } from "../../components/video-presentation";
import {
  Services,
  PublicationsPreview,
  AboutSummary,
  publicMeta,
} from "../../components/public-content";
const fallbackMeta = () =>
  publicMeta(
    "Исследование юридических документов",
    "ИИ-анализ юридических материалов и техническая подготовка документов. Предварительная консультация в SINEGOR LAB.",
  );
export const meta = ({ data }: Route.MetaArgs) =>
  data?.content ? contentMeta(data.content) : fallbackMeta();
export default function Home({ loaderData }: Route.ComponentProps) {
  const { content, services, articles, about } = loaderData;
  if (content)
    return (
      <div className="public-page">
        <section className="public-hero">
          <LabArt className="hero-art" />
          <div>
            <p className="eyebrow">SINEGOR LAB · Право и технологии</p>
            <h1>{content.title}</h1>
            <p className="lead">{content.summary}</p>
            <ContentSections content={content} />
            <Link className="button-link" to="/contacts#consultation">
              Запросить консультацию
            </Link>
          </div>
          <VideoPresentation
            src={content.video?.url}
            type={content.video?.mime}
            poster={content.image?.url}
            caption={content.videoCaption || undefined}
          />
        </section>
        <section>
          <h2>Услуги</h2>
          <div className="public-grid">
            {services
              .filter((service) => contentPath("services", service.slug))
              .map((service) => (
                <section className="card" key={service.slug}>
                  <h2>{service.title}</h2>
                  <p>{service.summary}</p>
                  <Link to={contentPath("services", service.slug)!}>
                    Подробнее об услуге
                  </Link>
                </section>
              ))}
          </div>
        </section>
        {about && (
          <section>
            <h2>Обо мне</h2>
            <p>{about.summary}</p>
            <Link to="/about">Об исполнителе</Link>
          </section>
        )}
        <section>
          <h2>Публикации</h2>
          <ArticleCards articles={articles} />
          <Link to="/publications">Все публикации</Link>
        </section>
      </div>
    );

  return (
    <div className="public-page">
      <section className="public-hero">
        <LabArt className="hero-art" />
        <div>
          <p className="eyebrow">SINEGOR LAB · Право и технологии</p>
          <h1>Исследование юридических документов</h1>
          <p className="lead">
            От массива материалов — к связной картине фактов.
          </p>
          <p>
            Поиск, сопоставление и систематизация информации с применением ИИ.
            Техническая подготовка документов как отдельная услуга.
          </p>
          <Link className="button-link" to="/contacts#consultation">
            Запросить консультацию
          </Link>
        </div>
        <VideoPresentation />
      </section>
      <Services />
      <section>
        <p className="eyebrow">Исполнитель</p>
        <h2>Обо мне</h2>
        <AboutSummary />
        <Link to="/about">Об исполнителе</Link>
      </section>
      <section>
        <h2>Публикации</h2>
        <PublicationsPreview />
        <Link to="/publications">Все публикации</Link>
      </section>
    </div>
  );
}
