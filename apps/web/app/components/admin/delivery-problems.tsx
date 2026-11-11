import { NotificationStatus } from "./notification-status";
import { Link, useSearchParams } from "react-router";
import type { Models } from "../../lib/admin/api";
import { date } from "../../lib/admin/labels";
import { Card, Notice } from "../ui";

const kinds: Record<string, string> = {
  materials_deleted: "Уведомление об удалении материалов",
  result_ready: "Уведомление о готовности результата",
  invitation: "Приглашение заказчика",
  magic_link: "Ссылка для входа",
  consultation: "Заявка на консультацию",
  consultation_telegram: "Уведомление о новой консультации",
  deletion_due: "Напоминание об удалении материалов",
  customer_blocked: "Уведомление о блокировке доступа",
  customer_unblocked: "Уведомление о восстановлении доступа",
  agreement_initial: "Соглашение направлено на подпись",
  agreement_returned: "Соглашение возвращено заказчиком",
  agreement_approved: "Соглашение утверждено",
  agreement_rejected: "Соглашение отклонено",
};
const reasons = {
  delayed: "Отправка задерживается более 24 часов.",
  permanent: "Автоматическая отправка остановлена из-за постоянной ошибки.",
  expired: "Срок автоматических повторов истёк.",
  temporary: "Временная ошибка отправки, ожидается повтор.",
};
const errors: Record<string, string> = {
  smtp_failed: "Временный сбой SMTP.",
  smtp_permanent: "Постоянная ошибка SMTP.",
  telegram_failed: "Временный сбой Telegram.",
  telegram_permanent: "Постоянная ошибка Telegram.",
  telegram_rate_limited: "Ограничение частоты запросов Telegram.",
  delivery_failed: "Внутренняя ошибка обработки уведомления.",
  contacts_expired: "Срок хранения контактов истёк.",
  manual_retry: "Запрошена ручная попытка отправки.",
};

export function DeliveryProblems({
  rows,
  start,
}: {
  start: number;
  rows: Models["DeliveryProblem"][];
}) {
  const [params] = useSearchParams();
  const firstPage = new URLSearchParams(params);
  firstPage.set("problems_offset", "0");
  return (
    <>
      <p>
        Здесь показаны проблемные уведомления всех видов по Email и Telegram.
        Статус «Отправлено» означает подтверждение SMTP или Telegram API, а не
        получение или прочтение сообщения адресатом.
      </p>
      {rows.length === 0 && (
        <Notice>
          {start === 0 ? (
            "Проблемных уведомлений нет"
          ) : (
            <>
              На этой странице проблемных уведомлений нет.{" "}
              <Link to={`?${firstPage}#notification-problems`}>
                В начало списка
              </Link>
            </>
          )}
        </Notice>
      )}
      <div className="consultation-list">
        {rows.map((row) => (
          <Card
            key={row.id}
            className="consultation-card"
            title={kinds[row.kind] || "Уведомление"}
          >
            <dl className="details">
              <dt>Создано</dt>
              <dd>{date(row.created_at)}</dd>
              <dt>Канал</dt>
              <dd>{row.channel === "smtp" ? "Email" : "Telegram"}</dd>
              <dt>Статус</dt>
              <dd>
                <NotificationStatus
                  status={row.status}
                  reason={row.reason}
                  manualRetry={row.error_code === "manual_retry"}
                />
              </dd>
              <dt>Причина</dt>
              <dd>{reasons[row.reason]}</dd>
            </dl>
            {row.attempts === 0 ? (
              <p>Попыток отправки не было.</p>
            ) : (
              <p>Попыток отправки: {row.attempts}.</p>
            )}
            <details>
              <summary>Подробности уведомления</summary>
              <p>
                Событие: <span>{row.id}</span>
              </p>
              {row.error_code && errors[row.error_code] && (
                <p>{errors[row.error_code]}</p>
              )}
            </details>
            {row.status === "pending" &&
              (row.reason !== "expired" ||
                row.error_code === "manual_retry") && (
                <p>
                  Следующая попытка (плановое время): {date(row.available_at)}.
                </p>
              )}
            <div className="actions">
              {row.order_id && (
                <Link to={`/admin/orders/${row.order_id}`}>Открыть заказ</Link>
              )}
              {row.customer_id && (
                <Link to={`/admin/customers/${row.customer_id}`}>
                  Открыть заказчика
                </Link>
              )}
              {["consultation", "consultation_telegram"].includes(row.kind) && (
                <Link to="/admin/consultations#consultation-requests">
                  Открыть консультационные заявки
                </Link>
              )}
            </div>
          </Card>
        ))}
      </div>
    </>
  );
}
