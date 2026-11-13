import { withPublicMetadata } from "../../lib/seo";
import { Link } from "react-router";
import { loadDocuments } from "../../lib/documents.server";
import { publicMeta } from "../../components/public-content";
import type { Route } from "./+types/documents";
export { DocumentError as ErrorBoundary } from "../../components/document-error";

export async function loader() {
  return { documents: await loadDocuments() };
}
export const headers: Route.HeadersFunction = () => ({
  "Cache-Control": "no-store",
});
function pageMeta({ data }: Route.MetaArgs) {
  return [
    ...publicMeta("Документы", "Правовая информация SINEGOR LAB"),
    ...(!data ? [{ name: "robots", content: "noindex, follow" }] : []),
  ];
}
export const meta = (args: Route.MetaArgs) =>
  withPublicMetadata(args, pageMeta(args));

export default function Documents({ loaderData }: Route.ComponentProps) {
  return (
    <section className="public-page">
      <p className="eyebrow">Правовая информация</p>
      <h1>Документы</h1>
      {loaderData.documents.length === 0 && (
        <p className="notice">Опубликованных документов пока нет.</p>
      )}
      <div className="public-grid document-catalog">
        {loaderData.documents.map((document) => (
          <section className="card" key={document.slug}>
            <h2>
              <Link to={`/documents/${encodeURIComponent(document.slug)}`}>
                {document.title}
              </Link>
            </h2>
          </section>
        ))}
      </div>
    </section>
  );
}
