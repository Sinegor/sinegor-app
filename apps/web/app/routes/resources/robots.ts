import type { Route } from "./+types/robots";
import { publicOrigin } from "../../lib/public-url.server";

export function loader({ request }: Route.LoaderArgs) {
  const origin = publicOrigin(request);
  return new Response(
    [
      "User-agent: *",
      "Allow: /",
      "Disallow: /auth/",
      "Disallow: /customer",
      "Disallow: /admin",
      "Disallow: /api/",
      "",
      `Sitemap: ${new URL("/sitemap.xml", origin).href}`,
      "",
    ].join("\n"),
    {
      headers: {
        "Content-Type": "text/plain; charset=utf-8",
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
      },
    },
  );
}
