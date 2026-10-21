import { redirect } from "react-router";
import { ApiError, browserApi, type createApiClient } from "../api/client";
import type { components } from "../api/schema";

export type Models = components["schemas"];
export type AdminApi = ReturnType<typeof createApiClient>;
export const PAGE_SIZE = 25;
export async function value<T>(request: Promise<{ data?: T }>): Promise<T> {
  const { data } = await request;
  if (data === undefined) throw new Error("Сервер вернул пустой ответ.");
  return data;
}
export async function optional<T>(request: Promise<T>): Promise<T | null> {
  try {
    return await request;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}
export async function adminLoad<T>(
  load: (api: AdminApi) => Promise<T>,
): Promise<T> {
  try {
    return await load(browserApi());
  } catch (error) {
    if (error instanceof ApiError && error.status === 401)
      throw redirect("/auth/admin");
    throw error;
  }
}
export function offset(url: URL, name = "offset") {
  const number = Number(url.searchParams.get(name) ?? 0);
  return Number.isSafeInteger(number) && number >= 0 ? number : 0;
}
export function message(error: unknown) {
  if (error instanceof ApiError) {
    const text =
      error.status === 409
        ? "Данные или условия операции изменились. Обновите карточку и проверьте их перед повтором."
        : error.status === 422
          ? "Проверьте заполненные поля и допустимость операции."
          : error.status === 413
            ? "PDF превышает допустимый размер на сервере."
            : error.status === 415
              ? "Нужен файл PDF."
              : error.status === 404
                ? "Запись не найдена или больше недоступна."
                : error.message;
    return text + (error.requestId ? ` Код обращения: ${error.requestId}` : "");
  }
  return "Не удалось выполнить действие. Проверьте соединение и повторите попытку.";
}
export function uploadInitial(
  api: AdminApi,
  id: string,
  revision: number,
  file: Blob,
) {
  return value(
    api.POST("/api/admin/orders/{order_id}/agreement/initial", {
      params: {
        path: { order_id: id },
        header: { "X-Agreement-Revision": revision },
      },
      headers: { "Content-Type": "application/pdf" },
      // OpenAPI represents binary bodies as strings; the serializer sends the original Blob.
      body: "",
      bodySerializer: () => file,
    }),
  );
}
export async function downloadAgreement(
  api: AdminApi,
  id: string,
  kind: "initial" | "returned" | "final",
) {
  const { data, response } = await api.GET(
    "/api/admin/orders/{order_id}/agreement/{kind}",
    {
      params: { path: { order_id: id, kind } },
      parseAs: "blob",
    },
  );
  const revision = Number(response.headers.get("X-Agreement-Revision"));
  if (!data || !Number.isSafeInteger(revision) || revision < 1)
    throw new Error("Не удалось определить версию PDF.");
  return { blob: data, revision };
}
export function savePdf(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
export function diskUrl(value: unknown): string | null {
  if (
    !value ||
    typeof value !== "object" ||
    !("folder_url" in value) ||
    typeof value.folder_url !== "string"
  )
    return null;
  try {
    const url = new URL(value.folder_url);
    return url.protocol === "https:" &&
      url.hostname === "disk.yandex.ru" &&
      !url.username &&
      !url.password &&
      !url.port
      ? url.href
      : null;
  } catch {
    return null;
  }
}
