import { withPublicMetadata } from "../../lib/seo";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import type { Route } from "./+types/contacts";
import { loadPage } from "../../lib/cms.server";
import { ContentSections, contentMeta } from "../../components/cms-content";
export const loader = () => loadPage("pages", "contacts");
import { Consultation } from "../../components/consultation";
import { ContentMedia } from "../../components/content-media";
import { publicMeta } from "../../components/public-content";
const fallbackMeta = () =>
  publicMeta("Контакты", "Запрос предварительной консультации в SINEGOR LAB.");
const pageMeta = ({ data }: Route.MetaArgs) =>
  data?.content ? contentMeta(data.content) : fallbackMeta();
export const meta = (args: Route.MetaArgs) =>
  withPublicMetadata(args, pageMeta(args));

export default function Contacts({ loaderData }: Route.ComponentProps) {
  const content = loaderData.content;
  const [sent, setSent] = useState(false);
  const successHeading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (sent) successHeading.current?.focus();
  }, [sent]);
  return (
    <div className="public-page public-prose">
      {sent ? (
        <h1 ref={successHeading} tabIndex={-1}>
          Заявка отправлена
        </h1>
      ) : content ? (
        <>
          <h1>Запросить консультацию</h1>
          <ContentMedia image={content.image} layout={content.imageLayout}>
            <p>{content.summary}</p>
            <ContentSections content={content} />
          </ContentMedia>
          {content.contactEmail && <p>Email: {content.contactEmail}</p>}
          {content.contactPhone && <p>Телефон: {content.contactPhone}</p>}
        </>
      ) : (
        <>
          <p className="eyebrow">Связаться</p>
          <h1>Запросить консультацию</h1>
          <p>Для связи с исполнителем оставьте запрос на консультацию.</p>
        </>
      )}
      <Consultation onSuccess={() => setSent(true)} />
      {sent && <Link to="/">На главную</Link>}
    </div>
  );
}
