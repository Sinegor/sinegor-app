import { useRef, useState, type ReactNode, type FormEvent } from "react";
import {
  Link,
  useNavigate,
  useRevalidator,
  useRouteError,
  isRouteErrorResponse,
  useSearchParams,
} from "react-router";
import { ApiError, browserApi } from "../../lib/api/client";
import {
  PAGE_SIZE,
  message,
  type AdminApi,
  type Models,
} from "../../lib/admin/api";
import { date, statuses, services, eventLabels } from "../../lib/admin/labels";
import { Button, Notice, Table } from "../ui";

export function useOperation() {
  const [busy, setBusy] = useState(false);
  const locked = useRef(false);
  const [notice, setNotice] = useState<{ text: string; error: boolean } | null>(
    null,
  );
  const navigate = useNavigate();
  const revalidator = useRevalidator();
  async function run<T>(
    operation: (api: AdminApi) => Promise<T>,
    success: string,
    failure?: string,
  ): Promise<T | undefined> {
    if (locked.current) return;
    locked.current = true;
    setBusy(true);
    setNotice(null);
    try {
      const result = await operation(browserApi());
      if (success) setNotice({ text: success, error: false });
      return result;
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        await navigate("/auth/admin", { replace: true });
        return;
      }
      setNotice({
        text: `${failure ? failure + " " : ""}${message(error)}`,
        error: true,
      });
    } finally {
      await revalidator.revalidate();
      locked.current = false;
      setBusy(false);
    }
  }
  return { run, busy: busy || revalidator.state !== "idle", notice, setNotice };
}
export type Operation = ReturnType<typeof useOperation>;
export function Feedback({ op }: { op: Operation }) {
  return op.notice && <Notice error={op.notice.error}>{op.notice.text}</Notice>;
}
export function AdminErrorBoundary() {
  const error = useRouteError();
  return (
    <section>
      <h1>Не удалось открыть раздел</h1>
      <Notice error>
        {isRouteErrorResponse(error) && error.status === 404
          ? "Страница не найдена."
          : message(error)}
      </Notice>
      <Link to="/admin/customers">Заказчики</Link>
      {" · "}
      <Link to="/auth/admin">Вход администратора</Link>
      <p>
        <Button onClick={() => window.location.reload()}>
          Повторить загрузку
        </Button>
      </p>
    </section>
  );
}
export function Loading() {
  return <Notice>Загрузка административной панели…</Notice>;
}
export function Pagination({
  count,
  start,
  name = "offset",
}: {
  count: number;
  start: number;
  name?: string;
}) {
  const [params] = useSearchParams();
  function to(offset: number) {
    const next = new URLSearchParams(params);
    next.set(name, String(offset));
    return `?${next}`;
  }
  return (
    <nav className="pagination" aria-label="Страницы списка">
      {start > 0 && <Link to={to(Math.max(0, start - PAGE_SIZE))}>Назад</Link>}
      <span>
        Записи {count ? start + 1 : 0}–{start + count}
      </span>
      {count === PAGE_SIZE && <Link to={to(start + PAGE_SIZE)}>Далее</Link>}
    </nav>
  );
}
export function OrdersTable({ rows }: { rows: Models["OrderRead"][] }) {
  return (
    <Table
      caption="Заказы"
      columns={["Номер", "Услуга", "Статус", "Стоимость", "Создан"]}
      rows={rows.map((row) => [
        <Link to={`/admin/orders/${row.id}`}>№ {row.number}</Link>,
        services[row.service_type],
        <span className={`badge ${row.status}`}>{statuses[row.status]}</span>,
        row.agreed_price == null ? "—" : `${row.agreed_price} ₽`,
        date(row.created_at),
      ])}
    />
  );
}
export function Events({
  events,
  start,
}: {
  events: Models["EventRead"][];
  start: number;
}) {
  return (
    <>
      <Table
        caption="Журнал событий"
        columns={["Дата", "Событие"]}
        rows={events.map((event) => [
          date(event.created_at),
          eventLabels[event.event_type] ?? event.event_type,
        ])}
      />
      <Pagination count={events.length} start={start} name="events_offset" />
    </>
  );
}
export function SelectField({
  label,
  name,
  value,
  children,
  required = false,
}: {
  label: string;
  name: string;
  value?: string;
  children: ReactNode;
  required?: boolean;
}) {
  return (
    <label className="field">
      {label}
      <select name={name} defaultValue={value} required={required}>
        {children}
      </select>
    </label>
  );
}
export function Check({
  name,
  children,
  required = true,
}: {
  name: string;
  children: ReactNode;
  required?: boolean;
}) {
  return (
    <label className="check">
      <input type="checkbox" name={name} required={required} />
      {children}
    </label>
  );
}
export function formData(event: FormEvent<HTMLFormElement>) {
  event.preventDefault();
  return new FormData(event.currentTarget);
}
export function text(data: FormData, name: string) {
  return String(data.get(name) ?? "").trim();
}
