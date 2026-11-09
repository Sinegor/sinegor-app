import { Link } from "react-router";
import type { FooterData, FooterLink } from "../lib/cms";
import { AnalyticsSettings } from "./public-analytics";

function FooterLinks({ links }: { links: FooterLink[] }) {
  return (
    <ul>
      {links.map((link, index) => (
        <li key={`${link.href}-${index}`}>
          {link.href.startsWith("/") ? (
            <Link to={link.href}>{link.label}</Link>
          ) : (
            <a href={link.href}>{link.label}</a>
          )}
        </li>
      ))}
    </ul>
  );
}

function FooterSection({
  id,
  title,
  links,
}: {
  id: string;
  title: string;
  links: FooterLink[];
}) {
  return (
    <nav aria-labelledby={id}>
      <h2 id={id}>{title}</h2>
      <FooterLinks links={links.slice(0, 5)} />
      {links.length > 5 && (
        <details className="footer-links-more">
          <summary>
            <span className="footer-show-all">Показать все</span>
            <span className="footer-collapse">Свернуть</span>
          </summary>
          <FooterLinks links={links.slice(5)} />
        </details>
      )}
    </nav>
  );
}

export function PublicFooter({
  year,
  data,
}: {
  year: number;
  data: FooterData;
}) {
  return (
    <footer className="public-footer">
      <div className="footer-columns">
        <div>
          <p className="brand-name">
            SINEGOR <span>LAB</span>
          </p>
          <p>IT-лаборатория адвоката Артемьева Д. В.</p>
        </div>
        <FooterSection
          id="footer-documents-title"
          title="Документы"
          links={data.documents}
        />
        <FooterSection
          id="footer-useful-title"
          title="Полезные ссылки"
          links={data.usefulLinks}
        />
      </div>
      <div className="footer-bottom">
        <p>© {year} SINEGOR LAB</p>
        <AnalyticsSettings />
      </div>
    </footer>
  );
}
