import { useState } from "react";
import {
  Link,
  useLoaderData,
  useRevalidator,
  type ClientLoaderFunctionArgs,
} from "react-router";
import {
  adminLoad,
  value,
  optional,
  offset,
  PAGE_SIZE,
} from "../../lib/admin/api";
import { date, services, statuses } from "../../lib/admin/labels";
import { Card, Form, Button, Modal, Notice } from "../../components/ui";
import {
  Check,
  Feedback,
  useOperation,
  formData,
  Events,
} from "../../components/admin/common";
import { TermsFields, terms } from "../../components/admin/terms";
import { AgreementPanel } from "../../components/admin/agreement";
import { FolderPanel } from "../../components/admin/folder";
import { RetentionPanel } from "../../components/admin/retention";
export { AdminErrorBoundary as ErrorBoundary } from "../../components/admin/common";
export const meta = () => [{ title: "Карточка заказа — SINEGOR LAB" }];
export function clientLoader({ params, request }: ClientLoaderFunctionArgs) {
  const id = params.orderId!,
    start = offset(new URL(request.url), "events_offset"),
    path = { order_id: id };
  const options = { params: { path }, signal: request.signal };
  return adminLoad(async (api) => {
    const order = await value(api.GET("/api/admin/orders/{order_id}", options));
    const [customer, agreement, materials, folder, deletion, events] =
      await Promise.all([
        value(
          api.GET("/api/admin/customers/{customer_id}", {
            params: { path: { customer_id: order.customer_id } },
            signal: request.signal,
          }),
        ),
        optional(
          value(api.GET("/api/admin/orders/{order_id}/agreement", options)),
        ),
        value(api.GET("/api/admin/orders/{order_id}/materials", options)),
        optional(
          value(api.GET("/api/admin/orders/{order_id}/folder", options)),
        ),
        value(
          api.GET("/api/admin/orders/{order_id}/deletion-request", options),
        ),
        value(
          api.GET("/api/admin/orders/{order_id}/events", {
            params: { path, query: { offset: start, limit: PAGE_SIZE } },
            signal: request.signal,
          }),
        ),
      ]);
    return {
      order,
      customer,
      agreement,
      materials,
      folder,
      deletion,
      events,
      start,
    };
  });
}
export default function Order() {
  const {
    order,
    customer,
    agreement,
    materials,
    folder,
    deletion,
    events,
    start,
  } = useLoaderData<typeof clientLoader>();
  const op = useOperation(),
    revalidator = useRevalidator();
  const [cancel, setCancel] = useState(false);
  const path = { order_id: order.id };
  return (
    <>
      <Link to="/admin/orders">← Заказы</Link>
      <div className="page-heading">
        <div>
          <p className="eyebrow">{services[order.service_type]}</p>
          <h1>Заказ № {order.number}</h1>
        </div>
        <Button disabled={op.busy} onClick={() => revalidator.revalidate()}>
          Обновить карточку
        </Button>
      </div>
      <Feedback op={op} />
      <div className="order-summary">
        <span className={`badge ${order.status}`}>
          {statuses[order.status]}
        </span>
        <Link to={`/admin/customers/${customer.id}`}>
          {customer.display_name || customer.email}
        </Link>
      </div>
      <dl className="facts">
        <dt>Создан</dt>
        <dd>{date(order.created_at)}</dd>
        <dt>Результат готов</dt>
        <dd>{date(order.ready_at)}</dd>
        <dt>Письмо принято SMTP</dt>
        <dd>{date(order.result_notified_at)}</dd>
        <dt>Заказ закрыт</dt>
        <dd>{date(order.closed_at)}</dd>
      </dl>
      <div className="admin-grid">
        <div>
          <Card title="Условия заказа">
            {order.status === "awaiting_agreement" && !agreement ? (
              <Form
                key={order.service_type}
                method="post"
                busy={op.busy}
                onSubmit={(event) => {
                  const data = formData(event);
                  void op.run(
                    (api) =>
                      value(
                        api.PUT("/api/admin/orders/{order_id}/terms", {
                          params: { path },
                          body: terms(data),
                        }),
                      ),
                    "Условия сохранены.",
                  );
                }}
              >
                <TermsFields order={order} />
                <Button type="submit">Сохранить условия</Button>
              </Form>
            ) : (
              <p>Условия зафиксированы для соглашения.</p>
            )}
          </Card>
          <AgreementPanel
            key={`${order.id}:${agreement?.revision ?? 0}`}
            order={order}
            agreement={agreement}
            op={op}
          />
          <FolderPanel
            key={`${order.id}:${folder?.deleted_at}:${folder?.deletion_started_at}`}
            orderId={order.id}
            folder={folder}
            op={op}
          />
          <RetentionPanel
            key={`${order.id}:${deletion?.id}:${deletion?.status}:${folder?.deletion_started_at}`}
            order={order}
            request={deletion}
            folder={folder}
            op={op}
          />
        </div>
        <div>
          <Card title="Передача материалов">
            <p>
              {materials
                ? `Заказчик отметил передачу ${date(materials.submitted_at)}`
                : "Отметки заказчика пока нет."}
            </p>
            {materials?.note && <p>{materials.note}</p>}
            <p>
              Получение и состав материалов проверяются на Яндекс Диске вручную.
            </p>
          </Card>
          <Card title="Изменение статуса">
            {order.status === "awaiting_materials" && (
              <Form
                method="post"
                busy={op.busy}
                onSubmit={(event) => {
                  formData(event);
                  void op.run(
                    (api) =>
                      value(
                        api.POST("/api/admin/orders/{order_id}/status", {
                          params: { path },
                          body: {
                            status: "in_progress",
                            result_uploaded: false,
                          },
                        }),
                      ),
                    "Заказ принят в работу.",
                  );
                }}
              >
                <Check name="materials_received">
                  Я получил материалы и подтверждаю начало работы
                </Check>
                <Button type="submit">Начать работу</Button>
              </Form>
            )}
            {order.status === "in_progress" && (
              <Form
                method="post"
                busy={op.busy}
                onSubmit={(event) => {
                  formData(event);
                  void op.run(
                    (api) =>
                      value(
                        api.POST("/api/admin/orders/{order_id}/status", {
                          params: { path },
                          body: {
                            status: "result_ready",
                            result_uploaded: true,
                          },
                        }),
                      ),
                    "Результат готов, письмо принято почтовым сервисом.",
                    "При сбое SMTP уведомление остаётся в очереди: обновите карточку перед повтором, статус может измениться после фоновой доставки.",
                  );
                }}
              >
                <Check name="result_uploaded">
                  Результат размещён в папке заказа
                </Check>
                <Button type="submit">Зафиксировать готовность</Button>
              </Form>
            )}
            {order.status === "result_ready" && (
              <p>
                Заказ завершится автоматически через 14 календарных дней после
                принятия письма SMTP. Подтверждение прочтения не требуется.
              </p>
            )}
            {order.status === "awaiting_agreement" && (
              <p>Для продолжения требуется утверждённое соглашение.</p>
            )}
            {["completed", "cancelled"].includes(order.status) && (
              <p>Заказ закрыт. Его статус больше не меняется.</p>
            )}
            {[
              "awaiting_agreement",
              "awaiting_materials",
              "in_progress",
            ].includes(order.status) && (
              <p>
                <Button
                  disabled={op.busy}
                  className="danger"
                  onClick={() => setCancel(true)}
                >
                  Отменить заказ
                </Button>
              </p>
            )}
          </Card>
        </div>
      </div>
      <Card title="История действий">
        <Events events={events} start={start} />
      </Card>
      <Modal
        busy={op.busy}
        open={cancel}
        title={`Отменить заказ № ${order.number}?`}
        onClose={() => {
          if (!op.busy) setCancel(false);
        }}
      >
        {cancel && op.notice?.error && <Notice error>{op.notice.text}</Notice>}
        <p>
          Заказ будет закрыт. Возобновить его через сайт нельзя. Материалы этим
          действием не удаляются.
        </p>
        <Button
          disabled={op.busy}
          className="danger"
          onClick={() =>
            op.run(async (api) => {
              await api.POST("/api/admin/orders/{order_id}/status", {
                params: { path },
                body: {
                  status: "cancelled",
                  result_uploaded: false,
                },
              });
              setCancel(false);
            }, "Заказ отменён.")
          }
        >
          Подтвердить отмену заказа
        </Button>
      </Modal>
    </>
  );
}
