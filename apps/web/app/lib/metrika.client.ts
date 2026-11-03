import { analyticsPath, createAnalytics } from "./analytics";

type Metrika = ((id: number, method: string, ...args: unknown[]) => unknown) & {
  a?: unknown[][];
  l?: number;
};
declare global {
  interface Window {
    ym?: Metrika;
  }
}

export function startMetrika(counterId: number) {
  let failed = false;
  let pending = true;
  const stub: Metrika = (...args) => {
    if (!failed && (stub.a?.length || 0) < 100) stub.a!.push(args);
  };
  stub.a = [];
  stub.l = Date.now();
  // A fresh queue prevents delayed initialization after leaving public routes.
  window.ym = stub;
  const script = document.createElement("script");
  script.src = "https://mc.yandex.ru/metrika/tag.js";
  script.async = true;
  script.referrerPolicy = "no-referrer";
  script.onload = () => {
    pending = false;
  };
  script.onerror = () => {
    failed = true;
    stub.a = [];
  };
  const analytics = createAnalytics(
    (method, ...args) => {
      if (
        failed ||
        (method !== "destruct" && !analyticsPath(window.location.pathname))
      )
        return;
      return window.ym?.(counterId, method, ...args);
    },
    window.location.origin,
    document.referrer,
  );
  document.head.append(script);
  return {
    ...analytics,
    dispose() {
      analytics.dispose();
      failed = true;
      if (pending) stub.a = [];
      script.onload = script.onerror = null;
      script.remove();
    },
  };
}
