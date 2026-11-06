import { useEffect, useState } from "react";
import {
  Link,
  useLoaderData,
  useRevalidator,
  type ClientLoaderFunctionArgs,
} from "react-router";
import { adminLoad, offset, PAGE_SIZE, value } from "../../lib/admin/api";
import { date } from "../../lib/admin/labels";
import {
  Feedback,
  Pagination,
  useOperation,
} from "../../components/admin/common";
import { Button, Card, Modal, Notice } from "../../components/ui";
export { AdminErrorBoundary as ErrorBoundary } from "../../components/admin/common";
export const meta = () => [{ title: "Проблемы доставки — SINEGOR LAB" }];

export function clientLoader({ request }: ClientLoaderFunctionArgs) {
  const url = new URL(request.url);
  const start = offset(url);
  const view =
    url.searchParams.get("view") === "handled" ? "handled" : "active";
  const observedAt = performance.now();
  return adminLoad(async (api) => ({
    observedAt,
    start,
    view,
    rows: await value(
      api.GET("/api/admin/consultations", {
        params: { query: { offset: start, limit: PAGE_SIZE, view } },
        signal: AbortSignal.any([request.signal, AbortSignal.timeout(5000)]),
      }),
    ),
  }));
}

const statuses = {
  pending: "ожидает отправки",
  processing: "отправляется",
  sent: "отправлено",
  cancelled: "отправка отменена",
  failed: "остановлено",
  expired: "автоматические повторы завершены",
};
const reasons = {
  permanent: "постоянная ошибка доставки",
  temporary: "временный сбой доставки",
  expired: "срок автоматических повторов истёк",
  awaiting: "ожидается попытка доставки",
};
const channelName = (channel: "smtp" | "telegram") =>
  channel === "smtp" ? "Email" : "Telegram";
type Choice =
  | { id: string; action: "handle" }
  | { id: string; action: "retry"; channel: "smtp" | "telegram" };

export default function Consultations() {
  const { rows, start, view, observedAt } =
    useLoaderData<typeof clientLoader>();
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
          <p className="eyebrow">Консультационные заявки</p>
          <h1>Проблемы доставки</h1>
        </div>
        <Button
          disabled={op.busy}
          onClick={() => void revalidator.revalidate()}
        >
          Обновить
        </Button>
      </div>
      <p>
        Контакты доступны до семи суток с обращения. Успешно отправленный канал
        повторно не отправляется.
      </p>
      <nav className="actions" aria-label="Состояние заявок">
        <Link
          to="/admin/consultations"
          aria-current={view === "active" ? "page" : undefined}
        >
          Недоставленные
        </Link>
        <Link
          to="/admin/consultations?view=handled"
          aria-current={view === "handled" ? "page" : undefined}
        >
          Обработанные
        </Link>
      </nav>
      <Feedback op={op} />
      {rows.length === 0 && (
        <Notice>
          {view === "handled"
            ? "Заявок, обработанных вручную, нет."
            : "Недоставленных консультационных заявок нет."}
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
                  Контакты недоступны: переданы по email, очищены после
                  обработки или срок доступа истёк.
                </p>
              )}
              {expiry(row.contacts_expires_at, row.observed_at) - now <=
                86400000 &&
                contactsVisible && (
                  <Notice tone="warning">
                    Контакты будут удалены менее чем через 24 часа. Обработайте
                    заявку до {date(row.contacts_expires_at)}.
                  </Notice>
                )}
              {contactsVisible && (
                <p>Контакты доступны до {date(row.contacts_expires_at)}.</p>
              )}
              <ul className="consultation-channels">
                {row.channels.map((channel) => (
                  <li key={channel.channel}>
                    <p>
                      {channelName(channel.channel)}: {statuses[channel.status]}
                    </p>
                    {channel.reason && (
                      <p>
                        {reasons[channel.reason]}
                        {channel.attention ? ". Требуется внимание." : ""}
                      </p>
                    )}
                    {channel.retry_after && (
                      <p>Повтор возможен после {date(channel.retry_after)}.</p>
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
      <Pagination count={rows.length} start={start} />
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
