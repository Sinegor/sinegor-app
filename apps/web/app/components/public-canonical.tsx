import { useLocation, useMatches, useRouteError } from "react-router";
import { canonicalUrl } from "../lib/public-url";

// This is the sole canonical emitter, shared by SSR and client navigation.
export function PublicCanonical() {
  const matches = useMatches();
  const location = useLocation();
  const error = useRouteError();
  const leaf = matches.at(-1);
  const data = matches.find((match) => match.id === "layouts/public")?.data as
    { publicOrigin: string } | undefined;
  if (
    error ||
    !data ||
    !leaf?.id.startsWith("routes/public/") ||
    leaf.data === undefined
  )
    return null;
  const href = canonicalUrl(
    data.publicOrigin,
    location.pathname,
    location.search,
  );
  return href ? <link rel="canonical" href={href} /> : null;
}
