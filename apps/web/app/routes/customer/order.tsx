import {
  Link,
  useLoaderData,
  useRevalidator,
  type ClientLoaderFunctionArgs,
} from "react-router";
import {
  customerLoad,
  value,
  optional,
  customerDiskUrl,
} from "../../lib/customer/api";
import { date, money, services, statuses } from "../../lib/admin/labels";
import { useOperation } from "../../components/admin/common";
import {
  Feedback,
  Check,
  formData,
  text,
} from "../../components/customer/common";
import { CustomerAgreement } from "../../components/customer/agreement";
import { CustomerRetention } from "../../components/customer/retention";
import { Button, Card, Field, Form, Notice } from "../../components/ui";
export { CustomerErrorBoundary as ErrorBoundary } from "../../components/customer/common";
export const meta = () => [{ title: "Мой заказ — SINEGOR LAB" }];
export function clientLoader({ request, params }: ClientLoaderFunctionArgs) {
  const path = { order_id: params.orderId! },
    options = { params: { path }, signal: request.signal };
  return customerLoad(async (api) => {
    const order = await value(
      api.GET("/api/customer/orders/{order_id}", options),
    );
    const [agreement, folder, materials, deletion] = await Promise.all([
      optional(
        value(api.GET("/api/customer/orders/{order_id}/agreement", options)),
      ),
      optional(
        value(api.GET("/api/customer/orders/{order_id}/folder", options)),
      ),
      value(api.GET("/api/customer/orders/{order_id}/materials", options)),
      value(
        api.GET("/api/customer/orders/{order_id}/deletion-request", options),
      ),
    ]);
    return {
      order,
      agreement,
      folderUrl: customerDiskUrl(folder),
      materials,
      deletion,
    };
  });
}
export default function CustomerOrder() {
  const { order, agreement, folderUrl, materials, deletion } =
    useLoaderData<typeof clientLoader>();
  const op = useOperation("/auth/login"),
    revalidator = useRevalidator();
  const ready =
    ["result_ready", "completed"].includes(order.status) &&
    !!order.result_notified_at;
  const canHandOver =
    ["awaiting_materials", "in_progress"].includes(order.status) &&
    agreement?.status === "approved" &&
    !materials;
  return (
    <>
      <Link to="/customer/orders">← Мои заказы</Link>
      <div className="page-heading">
        <div>
          <p className="eyebrow">{services[order.service_type]}</p>
          <h1>Заказ № {order.number}</h1>
        </div>
        <Button disabled={op.busy} onClick={() => revalidator.revalidate()}>
          Обновить заказ
        </Button>
      </div>
      <Feedback op={op} />
      <div className="order-summary">
        <span className={`badge ${order.status}`}>
          {statuses[order.status]}
        </span>
        <span>{money(order.agreed_price)}</span>
      </div>
      {ready && (
        <Notice>
          {deletion?.status === "performed" ? (
            "Материалы заказа удалены. Подписанное соглашение остаётся доступным в этой карточке."
          ) : (
            <>
              Результат предоставлен, уведомление отправлено{" "}
              {date(order.result_notified_at)}. Заберите результат через папку
              на Яндекс Диске. Заказ завершается автоматически через 14
              календарных дней после уведомления; удаление материалов отдельно
              подтверждает исполнитель.
            </>
          )}
        </Notice>
      )}
      <div className="customer-grid">
        <div>
          <Card title="Условия заказа">
            <dl className="facts">
              <dt>Услуга</dt>
              <dd>{services[order.service_type]}</dd>
              <dt>Стоимость</dt>
              <dd>{money(order.agreed_price)}</dd>
              <dt>Заказ создан</dt>
              <dd>{date(order.created_at)}</dd>
              {order.closed_at && (
                <>
                  <dt>Заказ закрыт</dt>
                  <dd>{date(order.closed_at)}</dd>
                </>
              )}
            </dl>
            {order.description && (
              <p className="pre-wrap">{order.description}</p>
            )}
          </Card>
          <CustomerAgreement
            key={`${order.id}:${agreement?.revision ?? 0}`}
            order={order}
            agreement={agreement}
            op={op}
          />
        </div>
        <div>
          <Card title={ready ? "Результат и папка заказа" : "Материалы заказа"}>
            {folderUrl ? (
              <>
                <p>
                  {ready
                    ? "Откройте папку заказа, чтобы получить результат."
                    : "Передайте документы непосредственно через интерфейс Яндекс Диска. Для доступа нужен аккаунт Яндекса."}
                </p>
                <a
                  className="button-link"
                  href={folderUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Открыть папку на Яндекс Диске ↗
                </a>
              </>
            ) : (
              <p>
                {deletion?.status === "performed"
                  ? "Материалы удалены, ссылка на папку больше недоступна."
                  : "Ссылка на папку пока недоступна. Если соглашение утверждено, уточните доступ у исполнителя."}
              </p>
            )}
            {materials && (
              <Notice>
                Передача материалов отмечена {date(materials.submitted_at)}.
                {materials.note && <p>{materials.note}</p>}
              </Notice>
            )}
            {canHandOver && (
              <Form
                method="post"
                busy={op.busy}
                onSubmit={(event) => {
                  const data = formData(event);
                  void op.run(
                    (api) =>
                      value(
                        api.POST("/api/customer/orders/{order_id}/materials", {
                          params: { path: { order_id: order.id } },
                          body: { note: text(data, "note") || null },
                        }),
                      ),
                    "Передача материалов отмечена. Исполнитель проверит их получение.",
                  );
                }}
              >
                <Field
                  label="Примечание к передаче (необязательно)"
                  name="note"
                  maxLength={2000}
                />
                <Check name="materials_uploaded">
                  Я завершил передачу материалов в папку заказа на Яндекс Диске
                </Check>
                <Button type="submit">Подтвердить передачу материалов</Button>
                <p className="muted">
                  Эта отметка не блокирует дальнейшую загрузку на Диск и сама не
                  начинает работу над заказом.
                </p>
              </Form>
            )}
          </Card>
          <CustomerRetention
            key={`${order.id}:${deletion?.id}:${deletion?.status}:${deletion?.early_authorized_at}`}
            order={order}
            request={deletion}
            op={op}
          />
        </div>
      </div>
    </>
  );
}
