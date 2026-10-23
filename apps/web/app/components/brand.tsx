import { Link } from "react-router";

export function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <Link className={`brand${compact ? " brand--compact" : ""}`} to="/">
      <span className="brand-name">
        SINEGOR <span>LAB</span>
      </span>
      <span className="brand-tagline">
        IT-лаборатория адвоката Артемьева Д. В.
      </span>
    </Link>
  );
}
