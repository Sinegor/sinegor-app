import { useState } from "react";
import type { Models } from "../../lib/customer/api";
import { date } from "../../lib/admin/labels";
import type { Operation } from "../admin/common";
import { Check, formData } from "./common";
import { Button, Card, Form, Modal, Notice } from "../ui";
const labels: Record<Models["DeletionStatus"], string> = {
  waiting: "Ожидается решение исполнителя",
  deferred: "Удаление отложено",
  confirmed: "Исполнитель подтвердил решение об удалении",
  error: "Требуется проверка удаления исполнителем",
  performed: "Материалы удалены",
};
export function CustomerRetention({
  order,
  request,
  op,
}: {
  order: Models["OrderRead"];
  request: Models["CustomerDeletionRead"] | null;
  op: Operation;
}) {
  const [confirming, setConfirming] = useState(false);
  const canAuthorize =
    ["result_ready", "completed"].includes(order.status) &&
    !!order.result_notified_at &&
    !request?.early_authorized_at &&
    (!request || ["waiting", "deferred"].includes(request.status));
  return (
    <Card title="Хранение и удаление материалов">
      <p>
        Завершение заказа и удаление исходных документов и результата происходят
        отдельно. Подписанное соглашение сохраняется.
      </p>
      {request ? (
        <>
          <p>
            <span className="badge">{labels[request.status]}</span>
          </p>
          {request.early_authorized_at && (
            <p>Ваше разрешение получено {date(request.early_authorized_at)}.</p>
          )}
          {request.deferred_until && (
            <p>Отсрочка удаления до {date(request.deferred_until)}.</p>
          )}
          {request.performed_at && (
            <p>Удаление проверено {date(request.performed_at)}.</p>
          )}
        </>
      ) : (
        <p>
          Материалы не удаляются автоматически. Решение об удалении отдельно
          подтверждает исполнитель.
        </p>
      )}
      {canAuthorize && (
        <>
          <p>
            Если дальнейшие уточнения с использованием материалов не нужны, вы
            можете разрешить их досрочное удаление.
          </p>
          <Button
            disabled={op.busy}
            onClick={() => {
              op.setNotice(null);
              setConfirming(true);
            }}
          >
            Разрешить удаление материалов
          </Button>
        </>
      )}
      <Modal
        open={confirming}
        busy={op.busy}
        title={`Разрешить удаление материалов заказа № ${order.number}?`}
        onClose={() => {
          if (!op.busy) setConfirming(false);
        }}
      >
        {confirming && op.notice?.error && (
          <Notice error>{op.notice.text}</Notice>
        )}
        <p>
          Удалению подлежат исходные документы и результат этого заказа.
          Подписанное соглашение и журнал сохраняются. Само удаление выполняется
          только после отдельного подтверждения исполнителя.
        </p>
        <Form
          method="post"
          busy={op.busy}
          key={String(confirming)}
          onSubmit={(event) => {
            formData(event);
            if (!canAuthorize) return;
            void op.run(async (api) => {
              await api.POST(
                "/api/customer/orders/{order_id}/deletion-permission",
                {
                  params: { path: { order_id: order.id } },
                  body: { confirm: true },
                },
              );
              setConfirming(false);
            }, "Разрешение сохранено. Удаление отдельно подтверждает исполнитель.");
          }}
        >
          <Check name="confirm">
            Разрешаю удалить материалы и отказываюсь от дальнейших уточнений,
            требующих их использования
          </Check>
          <Button type="submit" className="danger">
            Подтвердить разрешение на удаление
          </Button>
        </Form>
      </Modal>
    </Card>
  );
}
