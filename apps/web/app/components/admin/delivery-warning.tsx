import { useEffect, useState } from "react";
import { Link, useLocation, useRevalidator } from "react-router";
import { browserApi } from "../../lib/api/client";
import { value, type Models } from "../../lib/admin/api";
import { Notice } from "../ui";

const reasons = {
  temporary: "временная ошибка, ожидается повтор",
  delayed: "не доставлено более 24 часов",
  permanent: "постоянная ошибка",
  expired: "срок автоматических повторов истёк",
};

export function DeliveryWarning() {
  const location = useLocation();
  const revalidator = useRevalidator();
  const [delivery, setDelivery] = useState<
    Models["DeliverySummary"][] | null
  >();
  useEffect(() => {
    if (revalidator.state !== "idle") return;
    const api = browserApi();
    let disposed = false;
    let controller: AbortController | undefined;
    async function refresh() {
      if (controller) return;
      controller = new AbortController();
      const timeout = window.setTimeout(() => controller?.abort(), 5000);
      try {
        const summary = await value(
          api.GET("/api/admin/notifications/summary", {
            signal: controller.signal,
          }),
        );
        if (!disposed) setDelivery(summary);
      } catch {
        if (!disposed) setDelivery(null);
      } finally {
        window.clearTimeout(timeout);
        controller = undefined;
      }
    }
    void refresh();
    const interval = window.setInterval(() => {
      void refresh();
    }, 60000);
    return () => {
      disposed = true;
      window.clearInterval(interval);
      controller?.abort();
    };
  }, [location.key, revalidator.state]);

  if (delivery === undefined || delivery?.length === 0) return null;
  if (delivery === null) {
    return (
      <Notice tone="warning">Не удалось проверить доставку уведомлений.</Notice>
    );
  }
  return (
    <Notice tone="warning">
      <strong>Проблемы доставки</strong>
      <ul>
        {delivery.map((item) => (
          <li key={`${item.channel}:${item.reason}`}>
            {item.channel === "smtp" ? "Email" : "Telegram"}:{" "}
            {reasons[item.reason]} — {item.count}
          </li>
        ))}
      </ul>
      <Link to="/admin/consultations?view=notifications">
        Открыть проблемы доставки
      </Link>
    </Notice>
  );
}
