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

const codedMessages: Record<string, { status: number; message: string }> = {
  customer_name_invalid: {
    status: 422,
    message: "Укажите ФИО заказчика (не более 255 символов).",
  },
  csrf_failed: {
    status: 403,
    message: "Защита формы истекла. Обновите страницу и повторите действие.",
  },
  disk_invalid_path: {
    status: 422,
    message:
      "Проверьте путь: укажите папку внутри разрешённого каталога заказов на Яндекс Диске.",
  },
  disk_invalid_name: {
    status: 422,
    message:
      "Проверьте основу имени папки: недопустимые символы или слишком длинное имя.",
  },
  disk_folder_not_found: {
    status: 404,
    message:
      "Папка не найдена на Яндекс Диске. Проверьте путь и доступность папки.",
  },
  disk_access_denied: {
    status: 503,
    message:
      "У интеграции Яндекс Диска недостаточно прав. Проверьте токен и доступ к папке на Диске.",
  },
  disk_unavailable: {
    status: 503,
    message:
      "Яндекс Диск временно недоступен или интеграция не настроена. Проверьте настройки и повторите позже.",
  },
  disk_name_conflict: {
    status: 409,
    message:
      "Ресурс с таким именем уже существует. Укажите другую основу имени или проверьте папку и привяжите её явно.",
  },
};

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly requestId: string | null,
    public readonly customerId: string | null = null,
    code?: string,
  ) {
    super(
      code &&
        Object.hasOwn(codedMessages, code) &&
        codedMessages[code].status === status
        ? codedMessages[code].message
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
      typeof body.error.code === "string" &&
      Object.hasOwn(codedMessages, body.error.code)
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
