import { redirect } from "react-router";
import { normalizePublicPath, publicationOffset } from "./public-url";

export function publicOrigin(request: Request): string {
  // PUBLIC_ORIGIN is supplied at SSR runtime, independently of the CMS origin.
  const origin = new URL(
    process.env.PUBLIC_ORIGIN || new URL(request.url).origin,
  );
  if (
    !["http:", "https:"].includes(origin.protocol) ||
    origin.username ||
    origin.password ||
    origin.pathname !== "/" ||
    origin.search ||
    origin.hash
  )
    throw new Error("PUBLIC_ORIGIN must be an HTTP(S) origin without a path");
  return origin.origin;
}

export function documentUrl(request: Request): URL {
  const url = new URL(request.url);
  // Match the document URL used by React Router's configured single-fetch
  // protocol (v8_passThroughRequests + v8_trailingSlashAwareDataRequests).
  if (url.pathname.endsWith(".data")) {
    url.pathname = url.pathname.endsWith("/_.data")
      ? url.pathname.slice(0, -6)
      : url.pathname.slice(0, -5);
    url.searchParams.delete("_routes");
  }
  return url;
}

export function publicRedirect(request: Request): Response | null {
  if (!["GET", "HEAD"].includes(request.method)) return null;
  const url = documentUrl(request);
  const path = normalizePublicPath(url.pathname);
  if (path === null) return null;
  const original = url.pathname + url.search;
  url.pathname = path;
  if (path === "/publications") {
    const offset = publicationOffset(url.search);
    // Offset is the only query parameter that changes catalogue content.
    url.search = offset > 0 ? `?offset=${offset}` : "";
  }
  if (original === url.pathname + url.search) return null;
  // Do not infer the external origin from forwarded headers or enforce it against
  // the internal proxy-to-SSR URL, which could cause a redirect loop.
  return redirect(
    new URL(url.pathname + url.search, publicOrigin(request)).href,
    308,
  );
}
