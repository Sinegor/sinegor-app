import type { Models } from "../../lib/admin/api";

type Status = Models["ConsultationChannel"]["status"];
type Reason =
  Models["ConsultationChannel"]["reason"] | Models["DeliveryProblem"]["reason"];

export function notificationStatus(
  status: Status,
  reason: Reason,
  manualRetry = false,
) {
  if (status === "sent") return { label: "Отправлено", tone: "completed" };
  if (status === "cancelled") return { label: "Отправка отменена", tone: "" };
  if (status === "failed") return { label: "Ошибка отправки", tone: "error" };
  if (status === "expired")
    return { label: "Повторы прекращены", tone: "error" };
  if (status === "processing")
    return { label: "Отправляется", tone: "in_progress" };
  if (manualRetry) return { label: "Ожидает отправки", tone: "" };
  if (reason === "expired")
    return { label: "Повторы прекращены", tone: "error" };
  if (reason === "temporary")
    return { label: "Временная ошибка", tone: "waiting" };
  if (reason === "delayed")
    return { label: "Задержка отправки", tone: "waiting" };
  return { label: "Ожидает отправки", tone: "" };
}

export function NotificationStatus({
  status,
  reason,
  manualRetry = false,
}: {
  status: Status;
  reason: Reason;
  manualRetry?: boolean;
}) {
  const { label, tone } = notificationStatus(status, reason, manualRetry);
  return <span className={`badge ${tone}`}>{label}</span>;
}
