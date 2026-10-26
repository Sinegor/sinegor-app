import { Link } from "react-router";
import type { PageLink } from "../lib/cms";

export function PageLinks({ links }: { links: PageLink[] }) {
  if (!links.length) return null;
  return (
    <nav className="card related-pages" aria-labelledby="related-pages-heading">
      <h2 id="related-pages-heading">Материалы по теме</h2>
      <ul>
        {links.map((link) => (
          <li key={link.to}>
            <Link to={link.to}>{link.title}</Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
