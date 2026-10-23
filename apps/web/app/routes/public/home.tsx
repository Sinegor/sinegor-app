import { Link } from "react-router";
import {
  Services,
  PublicationsPreview,
  AboutSummary,
  publicMeta,
} from "../../components/public-content";
export const meta = () =>
  publicMeta(
    "Исследование юридических документов",
    "ИИ-анализ юридических материалов и техническая подготовка документов. Предварительная консультация в SINEGOR LAB.",
  );
export default function Home() {
  return (
    <div className="public-page">
      <section className="public-hero">
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
        <figure className="hero-video">
          <video
            controls
            playsInline
            preload="metadata"
            poster="/media/sinegor-lab-preview.jpg"
            aria-label="Временная видеопрезентация SINEGOR LAB"
          >
            <source src="/media/sinegor-lab-preview.mp4" type="video/mp4" />
            Ваш браузер не поддерживает видео.{" "}
            <a href="/media/sinegor-lab-preview.mp4">Скачать ролик</a>
          </video>
          <figcaption>
            Временный анимационный ролик. Полная видеопрезентация готовится.
            Ролик без звука: SINEGOR LAB — исследование и подготовка документов.
          </figcaption>
        </figure>
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
