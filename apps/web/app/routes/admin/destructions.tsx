import {
  Form,
  Link,
  useLoaderData,
  type ClientLoaderFunctionArgs,
} from "react-router";
import { adminLoad, offset, PAGE_SIZE, value } from "../../lib/admin/api";
import {
  Feedback,
  Pagination,
  SelectField,
  useOperation,
} from "../../components/admin/common";
import { Button, Card, Field, Notice } from "../../components/ui";
export { AdminErrorBoundary as ErrorBoundary } from "../../components/admin/common";
export const meta = () => [{ title: "Реестр уничтожения — SINEGOR LAB" }];

const kinds: Record<string, string> = {
  disk_folder: "Материалы заказа на Яндекс Диске",
  consultation_auto: "Автоматическая очистка консультации",
  consultation_manual: "Ручная очистка консультации",
  security_events: "Очистка журнала безопасности",
  customer_fields: "Удаление телефона заказчика",
  agreement: "Удаление подписанного соглашения",
  order_history: "Удаление истории заказа",
  customer: "Полное удаление карточки заказчика",
};
const states: Record<string, string> = {
  preparing: "Подготовка",
  executing: "Исполнение",
  verifying: "Проверка результата",
  error: "Ошибка",
  uncertain: "Исход не определён",
  documents_pending: "Ожидание документов",
  ready: "Документы готовы",
};
const date = (stamp: string) =>
  new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Europe/Moscow",
  }).format(new Date(stamp)) + " МСК";

export function clientLoader({ request }: ClientLoaderFunctionArgs) {
  const url = new URL(request.url);
  const start = offset(url);
  const q = url.searchParams.get("q") || "";
  const rawKind = url.searchParams.get("kind") || "";
  const rawState = url.searchParams.get("state") || "";
  const kind = Object.hasOwn(kinds, rawKind) ? rawKind : "";
  const state = Object.hasOwn(states, rawState) ? rawState : "";
  return adminLoad(async (api) => ({
    start,
    q,
    kind,
    state,
    rows: await value(
      api.GET("/api/admin/destructions", {
        params: {
          query: {
            q: q || undefined,
            kind: kind || undefined,
            state: state || undefined,
            limit: PAGE_SIZE,
            offset: start,
          },
        },
        signal: request.signal,
      }),
    ),
  }));
}

export default function Destructions() {
  const { rows, start, q, kind, state } = useLoaderData<typeof clientLoader>();
  const op = useOperation();
  return (
    <>
      <div className="page-heading">
        <h1>Реестр уничтожения</h1>
      </div>
      <p>
        Акты и выгрузки о подтверждённом уничтожении. Время — московское.
        Электронный акт нужно распечатать, дополнить и подписать; бумажный
        экземпляр хранится вне приложения.
      </p>
      <Form method="get" className="filter-bar" key={`${q}:${kind}:${state}`}>
        <input type="hidden" name="offset" value="0" />
        <Field
          label="Поиск по субъекту или ID"
          name="q"
          defaultValue={q}
          maxLength={320}
        />
        <SelectField label="Вид операции" name="kind" value={kind}>
          <option value="">Все операции</option>
          {Object.entries(kinds).map(([id, label]) => (
            <option key={id} value={id}>
              {label}
            </option>
          ))}
        </SelectField>
        <SelectField label="Результат" name="state" value={state}>
          <option value="">Все результаты</option>
          {Object.entries(states).map(([id, label]) => (
            <option key={id} value={id}>
              {label}
            </option>
          ))}
        </SelectField>
        <Button type="submit" variant="secondary">
          Применить фильтры
        </Button>
        <Link to="/admin/destructions">Сбросить фильтры</Link>
      </Form>
      <Feedback op={op} />
      {!rows.length && <Notice>Записей по выбранным условиям нет.</Notice>}
      <div className="consultation-list">
        {rows.map((row) => {
          const path = `/api/admin/destructions/${encodeURIComponent(row.id)}/documents`;
          const ready = row.state === "ready" && row.act_url && row.extract_url;
          const entity = row.metadata_json.entity;
          return (
            <Card
              key={row.id}
              title={kinds[row.kind] || "Операция уничтожения"}
            >
              <p>{row.subject || "Сведения о субъекте не сохранены"}</p>
              <p>
                <span className="badge">
                  {states[row.state] || "Неизвестное состояние"}
                </span>
              </p>
              <dl className="details">
                <dt>ID события</dt>
                <dd>{row.id}</dd>
                <dt>Создано</dt>
                <dd>{date(row.created_at)}</dd>
                {row.destroyed_at && (
                  <>
                    <dt>Уничтожение подтверждено</dt>
                    <dd>{date(row.destroyed_at)}</dd>
                  </>
                )}
                {row.expires_at && (
                  <>
                    <dt>Документы хранятся до</dt>
                    <dd>{date(row.expires_at)}</dd>
                  </>
                )}
                {typeof entity === "object" &&
                  entity !== null &&
                  Object.entries(entity).map(([key, val]) => (
                    <div key={key}>
                      <dt>
                        {(
                          {
                            order_id: "ID заказа",
                            customer_id: "ID заказчика",
                            batch_count: "Записей в партии",
                            notification_ids: "ID уведомлений",
                            resource_id: "ID папки",
                          } as Record<string, string>
                        )[key] || key}
                      </dt>
                      <dd>{String(val)}</dd>
                    </div>
                  ))}
              </dl>
              {!row.destroyed_at && (
                <Notice>Уничтожение не подтверждено.</Notice>
              )}
              {row.destroyed_at && !ready && (
                <Notice error={!!row.error_code}>
                  Уничтожение подтверждено; документы ещё не сформированы.
                </Notice>
              )}
              {ready && (
                <div className="actions">
                  <a
                    href={`${path}/act`}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Открыть акт
                  </a>
                  <a href={`${path}/act?download=true`}>Скачать акт</a>
                  <a
                    href={`${path}/extract`}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Открыть выгрузку
                  </a>
                  <a href={`${path}/extract?download=true`}>Скачать выгрузку</a>
                </div>
              )}
              {row.destroyed_at && !ready && (
                <Button
                  variant="secondary"
                  disabled={op.busy}
                  onClick={() =>
                    op.run(
                      async (api) => {
                        const result = await value(
                          api.POST(
                            "/api/admin/destructions/{identifier}/documents",
                            { params: { path: { identifier: row.id } } },
                          ),
                        );
                        if (result.state !== "ready")
                          throw new Error("documents pending");
                      },
                      "Документы сформированы.",
                      "Не удалось сформировать документы. Удаление повторно не выполняется.",
                    )
                  }
                >
                  Повторить формирование документов
                </Button>
              )}
            </Card>
          );
        })}
      </div>
      <Pagination count={rows.length} start={start} />
    </>
  );
}
