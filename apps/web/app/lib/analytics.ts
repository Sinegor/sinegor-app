import { canonicalUrl, normalizePublicPath } from "./public-url";

export type AnalyticsGoal =
  | "consultation_open"
  | "consultation_submit"
  | "service_view"
  | "video_presentation_view";
export type AnalyticsCommand = (method: string, ...args: unknown[]) => unknown;

export function analyticsPath(pathname: string, search = ""): string | null {
  const path = normalizePublicPath(pathname);
  if (!path) return null;
  const url = new URL(canonicalUrl("https://sinegor.invalid", path, search)!);
  return url.pathname + url.search;
}

function safeReferrer(value: string, origin: string) {
  try {
    const url = new URL(value);
    if (!["https:", "http:"].includes(url.protocol)) return `${origin}/`;
    if (url.origin !== origin) return `${url.origin}/`;
    const path = analyticsPath(url.pathname, url.search);
    return path ? `${origin}${path}` : `${origin}/`;
  } catch {
    return `${origin}/`;
  }
}

/** Only explicit, public URLs and fixed event names cross this boundary. */
export function createAnalytics(
  send: AnalyticsCommand,
  origin: string,
  referrer: string,
) {
  let active = true;
  let initialized = false;
  let previous: string | null = null;
  let current: string | null = null;
  const call: AnalyticsCommand = (method, ...args) => {
    try {
      const result = send(method, ...args);
      if (result instanceof Promise) void result.catch(() => {});
    } catch {
      /* Analytics must never interrupt navigation or forms. */
    }
  };
  const goal = (name: AnalyticsGoal, page: string) => {
    if (active && current && current === page) call("reachGoal", name);
  };
  return {
    page(pathname: string, search = "", recordView = true) {
      if (!active) return;
      current = analyticsPath(pathname, search);
      if (!current || current === previous) return;
      const referer = previous
        ? `${origin}${previous}`
        : safeReferrer(referrer, origin);
      const url = `${origin}${current}`;
      if (!initialized) {
        call("init", {
          defer: true,
          url,
          referrer: referer,
          webvisor: false,
          clickmap: false,
          trackLinks: false,
          accurateTrackBounce: false,
          trackHash: false,
          sendTitle: false,
          disableYtm: true,
          ecommerce: false,
        });
        initialized = true;
      }
      if (recordView)
        call("hit", url, {
          referer,
          title: "SINEGOR LAB",
          params: { event: "page_view" },
        });
      previous = current;
      if (recordView && current.startsWith("/services/"))
        goal("service_view", current);
    },
    goal,
    dispose() {
      if (active && initialized) call("destruct");
      active = false;
      current = null;
    },
  };
}
