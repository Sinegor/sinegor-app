import createClient from "openapi-fetch";
import type { paths } from "./schema";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly requestId: string | null,
    public readonly customerId: string | null = null,
  ) {
    super(
      status === 401
        ? "Необходимо войти в систему."
        : status === 403
          ? "Недостаточно прав или истекла защита формы. Обновите страницу."
          : status === 429
            ? "Слишком много запросов. Повторите позже."
            : "Не удалось выполнить запрос. Попробуйте ещё раз.",
    );
  }
}

// One client per browser page or server request; never share session state across SSR requests.
export function createApiClient(
  baseUrl: string,
  fetcher: typeof fetch = fetch,
) {
  const client = createClient<paths>({
    baseUrl,
    credentials: "same-origin",
    cache: "no-store",
    fetch: fetcher,
  });
  client.use({
    async onRequest({ request }) {
      if (!["GET", "HEAD", "OPTIONS"].includes(request.method)) {
        // Fetch for each mutation: login/logout changes the session binding of CSRF.
        const response = await fetcher(
          new Request(`${baseUrl}/api/auth/csrf`, {
            credentials: "same-origin",
            cache: "no-store",
            signal: request.signal,
          }),
        );
        if (!response.ok)
          throw new ApiError(
            response.status,
            response.headers.get("X-Request-ID"),
          );
        const body: unknown = await response.json();
        if (
          !body ||
          typeof body !== "object" ||
          !("csrf_token" in body) ||
          typeof body.csrf_token !== "string"
        ) {
          throw new Error("Не удалось получить защиту формы.");
        }
        request.headers.set("X-CSRF-Token", body.csrf_token);
      }
      return request;
    },
    onResponse({ response }) {
      if (!response.ok)
        throw new ApiError(
          response.status,
          response.headers.get("X-Request-ID"),
          response.headers.get("X-Customer-ID"),
        );
    },
    onError() {
      return new Error("Нет соединения с сервером. Повторите попытку.");
    },
  });
  return client;
}

export function browserApi() {
  return createApiClient(window.location.origin);
}
