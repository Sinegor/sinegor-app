import type { Route } from "./+types/technical";
import { loadPage } from "../../lib/cms.server";
import {
  ContentPage,
  ContentSections,
  contentMeta,
} from "../../components/cms-content";
export const loader = () => loadPage("services", "technical");
import { Link } from "react-router";
import { publicMeta } from "../../components/public-content";
const fallbackMeta = () =>
  publicMeta(
    "Техническая обработка",
    "Самостоятельная услуга по технической подготовке цифровых документов.",
  );
export const meta = ({ data }: Route.MetaArgs) =>
  data?.content ? contentMeta(data.content) : fallbackMeta();
export default function Page({ loaderData }: Route.ComponentProps) {
  const content = loaderData.content;
  if (content) return <ContentPage content={content} />;
  return (
    <article className="public-page public-prose">
      <p className="eyebrow">Услуги SINEGOR LAB</p>
      <h1>Техническая обработка</h1>
      <p>
        Подготовка цифровых документов может быть самостоятельным поручением без
        аналитического исследования.
      </p>
      <h2>Задачи обработки</h2>
      <ul>
        <li>Преобразование материалов в PDF.</li>
        <li>Формирование файлов под согласованную задачу.</li>
        <li>Добавление текстового слоя для поиска по документам.</li>
      </ul>
      <h2>Порядок работы</h2>
      <p>
        На консультации определяем состав материалов, необходимую обработку,
        сроки и стоимость. После согласования исполнитель оформляет заказ и
        предоставляет доступ в личный кабинет для обмена соглашением PDF.
      </p>
      <p>
        Исходные материалы и готовые файлы передаются через общую папку на
        Яндекс Диске. Для работы потребуется собственный аккаунт Яндекса.
      </p>
      <Link className="button-link" to="/contacts#consultation">
        Обсудить задачу
      </Link>
    </article>
  );
}
