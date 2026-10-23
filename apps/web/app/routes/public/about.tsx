import { Link } from "react-router";
import { AboutSummary, publicMeta } from "../../components/public-content";
export const meta = () =>
  publicMeta("Об исполнителе", "IT-лаборатория адвоката Артемьева Д. В.");
export default function About() {
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
