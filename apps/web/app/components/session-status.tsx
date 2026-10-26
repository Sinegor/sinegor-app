import { useEffect, useState } from "react";
import { ApiError, browserApi } from "../lib/api/client";
import { LoadingStatus, Notice } from "./ui";
export function SessionLoading() {
  return <LoadingStatus>Проверка сессии…</LoadingStatus>;
}
export function SessionStatus({ role }: { role: "admin" | "customer" }) {
  const [status, setStatus] = useState("Проверка сессии…");
  useEffect(() => {
    const controller = new AbortController();
    browserApi()
      .GET("/api/auth/session", { signal: controller.signal })
      .then(({ data }) => {
        if (!controller.signal.aborted)
          setStatus(
            data?.role === role
              ? "Сессия активна."
              : "Для этого раздела нужна другая роль.",
          );
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted)
          setStatus(
            error instanceof ApiError
              ? error.message
              : "Не удалось проверить соединение с сервером.",
          );
      });
    return () => controller.abort();
  }, [role]);
  return <Notice>{status}</Notice>;
}
