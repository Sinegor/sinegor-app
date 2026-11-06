import { Link } from "react-router";
import { loadDocument } from "../../lib/documents.server";
import { contentMeta } from "../../components/cms-content";
import { publicMeta } from "../../components/public-content";
import { CmsBlocks } from "../../components/cms-blocks";
import type { Route } from "./+types/document";
export { DocumentError as ErrorBoundary } from "../../components/document-error";

export async function loader({ params }: Route.LoaderArgs) {
  return loadDocument(params.slug);
}
export const headers: Route.HeadersFunction = () => ({
  "Cache-Control": "no-store",
});
export function meta({ data }: Route.MetaArgs) {
  return data?.content
    ? contentMeta(data.content)
    : [
        ...publicMeta("Документы", "Правовая информация SINEGOR LAB"),
        { name: "robots", content: "noindex, follow" },
      ];
}
export default function Document({ loaderData }: Route.ComponentProps) {
  const { title, content } = loaderData;
  return (
    <article className="public-page public-prose">
      <Link to="/documents">Все документы</Link>
      <h1>{title}</h1>
      {content.revisedOn && (
        <p className="muted">
          Редакция от{" "}
          <time dateTime={content.revisedOn}>
            {new Intl.DateTimeFormat("ru-RU", {
              dateStyle: "long",
              timeZone: "UTC",
            }).format(new Date(content.revisedOn))}
          </time>
        </p>
      )}
      <div className="cms-blocks">
        <CmsBlocks nodes={content.body} />
      </div>
      {content.pdf?.url && (
        <p>
          <a className="button-link" href={content.pdf.url}>
            Открыть PDF
          </a>
        </p>
      )}
    </article>
  );
}
