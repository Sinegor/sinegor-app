import type { Route } from "./+types/about";
import { loadPage } from "../../lib/cms.server";
import {
  ContentPage,
  ContentSections,
  contentMeta,
} from "../../components/cms-content";
export const loader = () => loadPage("pages", "about");
import { Link } from "react-router";
import { AboutSummary, publicMeta } from "../../components/public-content";
const fallbackMeta = () =>
  publicMeta("Об исполнителе", "IT-лаборатория адвоката Артемьева Д. В.");
export const meta = ({ data }: Route.MetaArgs) =>
  data?.content ? contentMeta(data.content) : fallbackMeta();
export default function About({ loaderData }: Route.ComponentProps) {
  const content = loaderData.content;
  if (content) return <ContentPage content={content} />;
  return (
    <article className="public-page public-prose">
      <p className="eyebrow">SINEGOR LAB</p>
      <h1>Об исполнителе</h1>
      <h2>Артемьев Д. В.</h2>
      <AboutSummary />
      <Link className="button-link" to="/contacts#consultation">
        Запросить консультацию
      </Link>
    </article>
  );
}
