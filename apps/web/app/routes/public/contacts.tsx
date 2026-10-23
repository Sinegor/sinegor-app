import type { Route } from "./+types/contacts";
import { loadPage } from "../../lib/cms.server";
import {
  ContentPage,
  ContentSections,
  contentMeta,
} from "../../components/cms-content";
export const loader = () => loadPage("pages", "contacts");
import { Consultation } from "../../components/consultation";
import { publicMeta } from "../../components/public-content";
const fallbackMeta = () =>
  publicMeta("Контакты", "Запрос предварительной консультации в SINEGOR LAB.");
export const meta = ({ data }: Route.MetaArgs) =>
  data?.content ? contentMeta(data.content) : fallbackMeta();
export default function Contacts({ loaderData }: Route.ComponentProps) {
  const content = loaderData.content;
  if (content)
    return (
      <div className="public-page public-prose">
        <h1>{content.title}</h1>
        <p>{content.summary}</p>
        <ContentSections content={content} />
        {content.contactEmail && <p>Email: {content.contactEmail}</p>}
        {content.contactPhone && <p>Телефон: {content.contactPhone}</p>}
        <Consultation />
      </div>
    );
  return (
    <div className="public-page public-prose">
      <p className="eyebrow">Связаться</p>
      <h1>Контакты</h1>
      <p>IT-лаборатория адвоката Артемьева Д. В.</p>
      <p>Для связи с исполнителем оставьте запрос на консультацию.</p>
      <Consultation />
    </div>
  );
}
