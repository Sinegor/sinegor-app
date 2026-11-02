import createClient from "openapi-fetch";
import type { paths } from "./schema";

const statusMessages: Record<number, string> = {
  401: "Необходимо войти в систему.",
  403: "Недостаточно прав или истекла защита формы. Обновите страницу.",
  404: "Запись не найдена или больше недоступна.",
  409: "Данные или условия операции изменились. Обновите карточку и проверьте их перед повтором.",
  413: "PDF превышает допустимый размер на сервере.",
  415: "Нужен файл PDF.",
  422: "Проверьте заполненные поля и допустимость операции.",
  429: "Слишком много запросов. Повторите позже.",
};

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly requestId: string | null,
    public readonly customerId: string | null = null,
    code?: string,
  ) {
    super(
      status === 403 && code === "csrf_failed"
        ? "Защита формы истекла. Обновите страницу и повторите действие."
        : (statusMessages[status] ??
            "Не удалось выполнить запрос. Попробуйте ещё раз."),
    );
  }
}

async function responseError(response: Response) {
  // Only a known machine code may refine our own copy. Never display API text,
  // validation inputs or exception details, including malformed error bodies.
  let code: string | undefined;
  try {
    const body: unknown = await response.clone().json();
    if (
      body &&
      typeof body === "object" &&
      "error" in body &&
      body.error &&
      typeof body.error === "object" &&
      "code" in body.error &&
      body.error.code === "csrf_failed"
    )
      code = body.error.code;
  } catch {
    /* Empty or non-JSON errors use the status fallback. */
  }
  return new ApiError(
    response.status,
    response.headers.get("X-Request-ID"),
    response.headers.get("X-Customer-ID"),
    code,
  );
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
        if (!response.ok) throw await responseError(response);
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
    async onResponse({ response }) {
      if (!response.ok) throw await responseError(response);
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
