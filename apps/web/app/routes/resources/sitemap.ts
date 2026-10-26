import type { Route } from "./+types/sitemap";
import { publicOrigin } from "../../lib/public-url.server";
import { renderSitemap, sitemapUrls } from "../../lib/sitemap.server";

export async function loader({ request }: Route.LoaderArgs) {
  const headers = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
  };
  try {
    const xml = renderSitemap(await sitemapUrls(publicOrigin(request)));
    return new Response(xml, {
      headers: { ...headers, "Content-Type": "application/xml; charset=utf-8" },
    });
  } catch {
    return new Response("Sitemap temporarily unavailable", {
      status: 503,
      headers: { ...headers, "Content-Type": "text/plain; charset=utf-8" },
    });
  }
}
