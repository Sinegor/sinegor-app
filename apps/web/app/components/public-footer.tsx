import { Link } from "react-router";
import { requiredDocumentLinks } from "../lib/documents";
import { AnalyticsSettings } from "./public-analytics";

export function PublicFooter({ year }: { year: number }) {
  return (
    <footer className="public-footer">
      <div>
        <p className="brand-name">
          SINEGOR <span>LAB</span>
        </p>
        <p>IT-лаборатория адвоката Артемьева Д. В.</p>
        <p className="footer-copyright">© {year} SINEGOR LAB</p>
      </div>
      <nav aria-labelledby="footer-legal-title">
        <h2 id="footer-legal-title">Правовая информация</h2>
        <ul>
          {requiredDocumentLinks.map((document) => (
            <li key={document.slug}>
              <Link to={`/documents/${document.slug}`}>{document.title}</Link>
            </li>
          ))}
          <li>
            <Link to="/about">Об исполнителе</Link>
          </li>
        </ul>
        <AnalyticsSettings />
      </nav>
    </footer>
  );
}
