import { useEffect, useState } from "react";
import {
  Link,
  useLoaderData,
  useLocation,
  useRevalidator,
  useSearchParams,
  type ClientLoaderFunctionArgs,
} from "react-router";
import { adminLoad, offset, PAGE_SIZE, value } from "../../lib/admin/api";
import { date } from "../../lib/admin/labels";
import {
  Feedback,
  Pagination,
  useOperation,
} from "../../components/admin/common";
import { NotificationStatus } from "../../components/admin/notification-status";
import { DeliveryProblems } from "../../components/admin/delivery-problems";
import { Button, Card, Modal, Notice } from "../../components/ui";
export { AdminErrorBoundary as ErrorBoundary } from "../../components/admin/common";
export const meta = () => [
  { title: "Контроль отправки уведомлений — SINEGOR LAB" },
];

export function clientLoader({ request }: ClientLoaderFunctionArgs) {
  const url = new URL(request.url);
  const view: "active" | "handled" =
    url.searchParams.get("view") === "handled" ? "handled" : "active";
  const legacyNotifications = url.searchParams.get("view") === "notifications";
  const problemStart = url.searchParams.has("problems_offset")
    ? offset(url, "problems_offset")
    : legacyNotifications
      ? offset(url)
      : 0;
  const start = url.searchParams.has("consultations_offset")
    ? offset(url, "consultations_offset")
    : legacyNotifications
      ? 0
      : offset(url);
  const observedAt = performance.now();
  return adminLoad(async (api) => {
    const signal = AbortSignal.any([request.signal, AbortSignal.timeout(5000)]);
    const [problems, rows] = await Promise.all([
      value(
        api.GET("/api/admin/notifications/problems", {
          params: { query: { offset: problemStart, limit: PAGE_SIZE } },
          signal,
        }),
      ),
      value(
        api.GET("/api/admin/consultations", {
          params: { query: { offset: start, limit: PAGE_SIZE, view } },
          signal,
        }),
      ),
    ]);
    return { observedAt, start, problemStart, view, problems, rows };
  });
}

const reasons = {
  permanent: "Автоматическая отправка остановлена из-за постоянной ошибки.",
  temporary: "Временная ошибка отправки, ожидается повтор.",
  expired: "Срок автоматических повторов истёк.",
  awaiting: "Ожидается попытка отправки.",
};
const channelName = (channel: "smtp" | "telegram") =>
  channel === "smtp" ? "Email" : "Telegram";
type Choice =
  | { id: string; action: "handle" }
  | { id: string; action: "retry"; channel: "smtp" | "telegram" };

export default function Consultations() {
  const { rows, problems, start, problemStart, view, observedAt } =
    useLoaderData<typeof clientLoader>();
  const [params] = useSearchParams();
  const location = useLocation();
  const problemsActive =
    location.hash === "#notification-problems" ||
    (!location.hash && params.get("view") === "notifications");
  const sectionParams = new URLSearchParams(params);
  sectionParams.delete("offset");
  sectionParams.set("problems_offset", String(problemStart));
  sectionParams.set("consultations_offset", String(start));
  function consultationLink(nextView: "active" | "handled") {
    const next = new URLSearchParams(params);
    next.set("view", nextView);
    next.delete("offset");
    next.set("consultations_offset", "0");
    next.set("problems_offset", String(problemStart));
    return `?${next}#consultation-requests`;
  }
  const op = useOperation();
  const revalidator = useRevalidator();
  const [choice, setChoice] = useState<Choice | null>(null);
  const [now, setNow] = useState(performance.now.bind(performance));
  const expiry = (deadline: string, serverTime: string) =>
    observedAt + Date.parse(deadline) - Date.parse(serverTime);
  useEffect(() => {
    const interval = window.setInterval(() => {
      if (revalidator.state === "idle") void revalidator.revalidate();
    }, 60000);
    return () => window.clearInterval(interval);
  }, [revalidator]);
  useEffect(() => {
    let timeout: number | undefined;
    function tick() {
      const current = performance.now();
      setNow(current);
      const next = Math.min(
        ...rows
          .map((row) => expiry(row.contacts_expires_at, row.observed_at))
          .filter((time) => time > current),
      );
      if (Number.isFinite(next))
        timeout = window.setTimeout(
          tick,
          Math.min(next - current + 1, 2147483647),
        );
    }
    tick();
    return () => window.clearTimeout(timeout);
  }, [rows, observedAt]);
  const selected = rows.find((row) => row.id === choice?.id);
  const retryAvailable =
    selected &&
    selected.can_retry &&
    now < expiry(selected.contacts_expires_at, selected.observed_at);

  async function confirm() {
    if (!choice) return;
    const chosen = choice;
    await op.run(
      async (api) => {
        if (chosen.action === "retry")
          await api.POST("/api/admin/consultations/{identifier}/retry", {
            params: { path: { identifier: chosen.id } },
            body: { confirmed: true, channel: chosen.channel },
          });
        else
          await api.POST("/api/admin/consultations/{identifier}/handle", {
            params: { path: { identifier: chosen.id } },
            body: { confirmed: true },
          });
      },
      chosen.action === "retry"
        ? "Повтор отправки запрошен. Проверьте состояние канала."
        : "Заявка отмечена обработанной. Контакты очищены.",
    );
    setChoice(null);
  }

  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">Административная панель</p>
          <h1>Контроль отправки уведомлений</h1>
        </div>
        <Button
          disabled={op.busy}
          onClick={() => void revalidator.revalidate()}
        >
          Обновить
        </Button>
      </div>
      <nav
        className="notification-navigation"
        aria-label="Разделы контроля отправки"
      >
        <Link
          to={`?${sectionParams}#notification-problems`}
          aria-current={problemsActive ? "location" : undefined}
        >
          Проблемные уведомления
        </Link>
        <Link
          to={`?${sectionParams}#consultation-requests`}
          aria-current={!problemsActive ? "location" : undefined}
        >
          Консультационные заявки
        </Link>
      </nav>
      <section
        id="notification-problems"
        className="notification-section"
        aria-labelledby="notification-problems-title"
      >
        <h2 id="notification-problems-title">Проблемные уведомления</h2>
        <DeliveryProblems rows={problems} start={problemStart} />
        <Pagination
          count={problems.length}
          start={problemStart}
          name="problems_offset"
        />
      </section>
      <section
        id="consultation-requests"
        className="notification-section"
        aria-labelledby="consultation-requests-title"
      >
        <h2 id="consultation-requests-title">Консультационные заявки</h2>
        <p>
          Контакты доступны до семи суток с обращения. Успешно отправленный
          канал повторно не отправляется. Отметка о ручной обработке не означает
          успешную отправку уведомлений.
        </p>
        <nav className="notification-navigation" aria-label="Состояние заявок">
          <Link
            to={consultationLink("active")}
            aria-current={view === "active" ? "page" : undefined}
          >
            Отправка не завершена
          </Link>
          <Link
            to={consultationLink("handled")}
            aria-current={view === "handled" ? "page" : undefined}
          >
            Обработаны вручную
          </Link>
        </nav>
        <Feedback op={op} />
        {rows.length === 0 && (
          <Notice>
            {start > 0 ? (
              <>
                На этой странице консультационных заявок нет.{" "}
                <Link to={consultationLink(view)}>В начало списка заявок</Link>
              </>
            ) : view === "handled" ? (
              "Заявок, обработанных вручную, нет."
            ) : (
              "Консультационных заявок с незавершённой отправкой нет."
            )}
          </Notice>
        )}
        <div className="consultation-list">
          {rows.map((row) => {
            const beforeDeadline =
              now < expiry(row.contacts_expires_at, row.observed_at);
            const contactsVisible = beforeDeadline && !!row.email;
            return (
              <Card
                key={row.id}
                className="consultation-card"
                title={`Обращение от ${date(row.created_at)}`}
              >
                <p>
                  <strong>
                    {row.status === "handled"
                      ? "Обработано вручную"
                      : "Требует обработки"}
                  </strong>
                </p>
                {contactsVisible ? (
                  <dl className="details">
                    <dt>Email</dt>
                    <dd>{row.email}</dd>
                    <dt>Телефон</dt>
                    <dd>{row.phone || "Не указан"}</dd>
                  </dl>
                ) : (
                  <p>
                    Контакты недоступны: очищены после отправки email, ручной
                    обработки или истечения срока доступа.
                  </p>
                )}
                {expiry(row.contacts_expires_at, row.observed_at) - now <=
                  86400000 &&
                  contactsVisible && (
                    <Notice tone="warning">
                      Контакты будут удалены менее чем через 24 часа.
                      Обработайте заявку до {date(row.contacts_expires_at)}.
                    </Notice>
                  )}
                {contactsVisible && (
                  <p>Контакты доступны до {date(row.contacts_expires_at)}.</p>
                )}
                <ul className="consultation-channels">
                  {row.channels.map((channel) => (
                    <li key={channel.channel}>
                      <p>
                        {channelName(channel.channel)}:{" "}
                        <NotificationStatus
                          status={channel.status}
                          reason={channel.reason}
                        />
                      </p>
                      {channel.reason && (
                        <p>
                          {reasons[channel.reason]}
                          {channel.attention ? " Требуется внимание." : ""}
                        </p>
                      )}
                      {channel.retry_after && (
                        <p>
                          Повтор возможен после {date(channel.retry_after)}.
                        </p>
                      )}
                      {row.can_retry &&
                        beforeDeadline &&
                        ["pending", "failed", "expired"].includes(
                          channel.status,
                        ) && (
                          <Button
                            disabled={op.busy || !!channel.retry_after}
                            onClick={() =>
                              setChoice({
                                id: row.id,
                                action: "retry",
                                channel: channel.channel,
                              })
                            }
                          >
                            Повторить отправку: {channelName(channel.channel)}
                          </Button>
                        )}
                    </li>
                  ))}
                </ul>
                {row.can_handle && (
                  <Button
                    disabled={op.busy}
                    onClick={() => setChoice({ id: row.id, action: "handle" })}
                  >
                    Отметить обработанным
                  </Button>
                )}
              </Card>
            );
          })}
        </div>
        <Pagination
          count={rows.length}
          start={start}
          name="consultations_offset"
        />
      </section>
      <Modal
        open={choice !== null}
        title={
          choice?.action === "retry"
            ? "Повторить отправку?"
            : "Отметить заявку обработанной?"
        }
        busy={op.busy}
        onClose={() => {
          if (!op.busy) setChoice(null);
        }}
      >
        {choice?.action === "retry" ? (
          <p>
            Повторить отправку через {channelName(choice.channel)}. Уже успешный
            канал не повторяется. При потере подтверждения провайдера возможен
            дубликат.
          </p>
        ) : (
          <p>
            Обращение обработано вне сайта. Оставшиеся отправки будут отменены.
            Контакты будут очищены, останется отметка о ручной обработке.
          </p>
        )}
        {choice?.action === "retry" && !retryAvailable && (
          <Notice tone="warning">
            Повтор больше недоступен. Обновите список.
          </Notice>
        )}
        <div className="actions">
          <Button
            disabled={
              op.busy ||
              !selected ||
              (choice?.action === "retry"
                ? !retryAvailable
                : !selected.can_handle)
            }
            onClick={() => void confirm()}
          >
            {choice?.action === "retry"
              ? "Подтвердить отправку"
              : "Подтвердить обработку"}
          </Button>
        </div>
      </Modal>
    </>
  );
}
