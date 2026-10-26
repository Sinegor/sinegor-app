import { replace } from "react-router";
import { ApiError, browserApi } from "./client";

export async function loginLoader({ request }: { request: Request }) {
  let principal;
  try {
    const { data } = await browserApi().GET("/api/auth/session", {
      signal: request.signal,
    });
    principal = data;
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null;
    throw error;
  }
  if (!principal) throw new Error("Сервер вернул пустой ответ.");
  throw replace(
    principal.role === "admin" ? "/admin/customers" : "/customer/orders",
  );
}
loginLoader.hydrate = true as const;
