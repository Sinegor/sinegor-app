import {
  Form,
  Link,
  useLoaderData,
  type ClientLoaderFunctionArgs,
} from "react-router";
import {
  adminLoad,
  offset,
  PAGE_SIZE,
  value,
  type Models,
} from "../../lib/admin/api";
import { Pagination, SelectField } from "../../components/admin/common";
import { Button, Card, Field, Notice } from "../../components/ui";
export { AdminErrorBoundary as ErrorBoundary } from "../../components/admin/common";
export const meta = () => [{ title: "События безопасности — SINEGOR LAB" }];

type Event = Models["SecurityEventRead"];
const eventTypes: Record<Event["event_type"], string> = {
  authentication: "Аутентификация",
  rate_limit: "Лимит попыток",
  access_denied: "Отказ доступа",
  credential_issued: "Выдача средства доступа",
  credential_revoked: "Отзыв средства доступа",
  privilege_changed: "Изменение полномочий",
};
const reasons: Record<Event["reason_code"], string> = {
  customer_blocked: "Доступ заказчика заблокирован",
  customer_unblocked: "Доступ заказчика восстановлен",
  admin_login: "Вход администратора",
  magic_link_login: "Вход по одноразовой ссылке",
  invalid_credentials: "Неверные или истёкшие данные входа",
  invalid_request: "Некорректные данные запроса входа",
  attempt_limit: "Превышен лимит попыток",
  authentication_required: "Требуется действующая сессия",
  admin_required: "Требуются права администратора",
  customer_required: "Требуются права заказчика",
  order_not_owned: "Заказ недоступен заказчику",
  csrf_failed: "Проверка безопасности запроса не пройдена",
  session_created: "Сессия создана",
  session_rotated: "Предыдущая сессия отозвана при входе",
  logout: "Выход из системы",
  magic_link_issued: "Одноразовая ссылка создана",
  invitation_issued: "Приглашение создано",
  link_replaced: "Предыдущие ссылки заменены",
  link_consumed: "Одноразовая ссылка использована",
  delivery_failed: "Ссылка отозвана из-за ошибки доставки",
  email_changed: "Средства доступа отозваны при смене email",
  admin_created: "Учётная запись администратора создана",
  agreement_required: "Доступ к папке до утверждения соглашения запрещён",
};
const utcDate = (value: string) =>
  new Intl.DateTimeFormat("ru-RU", {
    dateStyle: "short",
    timeStyle: "medium",
    timeZone: "UTC",
  }).format(new Date(value));

export function clientLoader({ request }: ClientLoaderFunctionArgs) {
  const url = new URL(request.url);
  const start = offset(url);
  const from = url.searchParams.get("date_from") || "";
  const to = url.searchParams.get("date_to") || "";
  const raw = url.searchParams.get("event_type") || "";
  const kind = Object.hasOwn(eventTypes, raw)
    ? (raw as Event["event_type"])
    : undefined;
  return adminLoad(async (api) => ({
    start,
    from,
    to,
    kind,
    rows: await value(
      api.GET("/api/admin/security-events", {
        params: {
          query: {
            date_from: from || undefined,
            date_to: to || undefined,
            event_type: kind,
            offset: start,
            limit: PAGE_SIZE,
          },
        },
        signal: request.signal,
      }),
    ),
  }));
}

export default function SecurityEvents() {
  const { rows, start, from, to, kind } = useLoaderData<typeof clientLoader>();
  return (
    <>
      <div className="page-heading">
        <h1>События безопасности</h1>
      </div>
      <p>
        Журнал доступен только для просмотра. Даты и время в этом разделе
        указаны в UTC.
      </p>
      <Form className="filter-bar" method="get" key={`${from}:${to}:${kind}`}>
        <Field
          label="Дата с (UTC)"
          type="date"
          name="date_from"
          defaultValue={from}
          max={to || undefined}
        />
        <Field
          label="Дата по (UTC)"
          type="date"
          name="date_to"
          defaultValue={to}
          min={from || undefined}
        />
        <SelectField label="Тип события" name="event_type" value={kind || ""}>
          <option value="">Все типы</option>
          {Object.entries(eventTypes).map(([id, label]) => (
            <option key={id} value={id}>
              {label}
            </option>
          ))}
        </SelectField>
        <Button type="submit" variant="secondary">
          Применить фильтры
        </Button>
        <Link to="/admin/security-events">Сбросить фильтры</Link>
      </Form>
      {!rows.length && <Notice>Событий по выбранным условиям нет.</Notice>}
      <div className="consultation-list">
        {rows.map((row) => (
          <Card key={row.id} title={eventTypes[row.event_type]}>
            <p>
              <time dateTime={row.recorded_at}>
                {utcDate(row.recorded_at)} UTC
              </time>{" "}
              · {row.result === "success" ? "Успех" : "Отказ"}
            </p>
            <p>{reasons[row.reason_code]}</p>
            <dl className="details">
              <dt>Пользователь</dt>
              <dd>
                {row.user_id
                  ? `${row.user_role === "admin" ? "Администратор" : "Заказчик"}: ${row.user_id}`
                  : "Личность не установлена"}
              </dd>
              {row.subject_user_id && (
                <>
                  <dt>Затронутая учётная запись</dt>
                  <dd>{row.subject_user_id}</dd>
                </>
              )}
              <dt>ID события</dt>
              <dd>{row.id}</dd>
              <dt>ID запроса</dt>
              <dd>{row.request_id}</dd>
              <dt>Код причины</dt>
              <dd>{row.reason_code}</dd>
            </dl>
          </Card>
        ))}
      </div>
      <Pagination count={rows.length} start={start} />
    </>
  );
}
