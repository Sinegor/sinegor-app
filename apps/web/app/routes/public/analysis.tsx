import { withPublicMetadata } from "../../lib/seo";
import type { Route } from "./+types/analysis";
import { loadPage } from "../../lib/cms.server";
import {
  ContentPage,
  ContentSections,
  contentMeta,
} from "../../components/cms-content";
export const loader = () => loadPage("services", "ai-analysis");
import { Link } from "react-router";
import { publicMeta } from "../../components/public-content";
const fallbackMeta = () =>
  publicMeta(
    "ИИ-анализ документов",
    "Исследование больших массивов юридических материалов с применением ИИ.",
  );
const pageMeta = ({ data }: Route.MetaArgs) =>
  data?.content ? contentMeta(data.content) : fallbackMeta();
export const meta = (args: Route.MetaArgs) =>
  withPublicMetadata(args, pageMeta(args));

export default function Page({ loaderData }: Route.ComponentProps) {
  const content = loaderData.content;
  if (content) return <ContentPage content={content} />;
  return (
    <article className="public-page public-prose">
      <p className="eyebrow">Услуги SINEGOR LAB</p>
      <h1>ИИ-анализ документов</h1>
      <p>
        Исследуются юридические документы различных категорий. Состав работы
        зависит от конкретного поручения.
      </p>
      <h2>Что может входить в исследование</h2>
      <ul>
        <li>Поиск, извлечение и фильтрация сведений.</li>
        <li>Отбор документов по датам, типам и другим признакам.</li>
        <li>
          Группировка и сопоставление фактической информации, включая показания
          конкретных лиц.
        </li>
        <li>
          Установление связей, возможных фактических несоответствий и хронологии
          событий.
        </li>
      </ul>
      <h2>Как проходит работа</h2>
      <p>
        Сначала обсуждаем задачу и согласуем объём, сроки, стоимость и формат
        результата. После консультации исполнитель создаёт заказ и приглашает
        вас в личный кабинет. Соглашение подписывается путём обмена PDF.
      </p>
      <p>
        Материалы и результат передаются непосредственно через папку заказа на
        Яндекс Диске. О готовности результата приходит уведомление.
      </p>
      <Link className="button-link" to="/contacts#consultation">
        Обсудить задачу
      </Link>
    </article>
  );
}
