import { redirect } from "react-router";
import { ApiError, browserApi } from "../api/client";
import { value, diskUrl, type AdminApi as Api } from "../admin/api";
export { value, optional, savePdf } from "../admin/api";
export type { Models } from "../admin/api";

export async function customerLoad<T>(
  load: (api: Api) => Promise<T>,
): Promise<T> {
  try {
    return await load(browserApi());
  } catch (error) {
    if (error instanceof ApiError && error.status === 401)
      throw redirect("/auth/login");
    throw error;
  }
}
export function uploadReturned(
  api: Api,
  id: string,
  revision: number,
  file: Blob,
) {
  return value(
    api.POST("/api/customer/orders/{order_id}/agreement/returned", {
      params: {
        path: { order_id: id },
        header: { "X-Agreement-Revision": revision },
      },
      headers: { "Content-Type": "application/pdf" },
      body: "",
      bodySerializer: () => file,
    }),
  );
}
export async function downloadCustomerAgreement(
  api: Api,
  id: string,
  kind: "initial" | "returned" | "final",
) {
  const { data, response } = await api.GET(
    "/api/customer/orders/{order_id}/agreement/{kind}",
    { params: { path: { order_id: id, kind } }, parseAs: "blob" },
  );
  const revision = Number(response.headers.get("X-Agreement-Revision"));
  if (!data || !Number.isSafeInteger(revision) || revision < 1)
    throw new Error("Не удалось получить соглашение.");
  return { blob: data, revision };
}
export function customerDiskUrl(data: unknown) {
  const url = diskUrl(data);
  if (!url) return null;
  return new URL(url).pathname.startsWith("/client/") ||
    new URL(url).pathname.startsWith("/invite/")
    ? url
    : null;
}
