import { useState } from "react";
import type { Models } from "../../lib/admin/api";
import { date, deletions } from "../../lib/admin/labels";
import { Button, Card, Form, Field, Modal, Notice } from "../ui";
import { Check, formData, text, type Operation } from "./common";
export function moscowDate(value: string) {
  return new Date(`${value}+03:00`).toISOString();
}
function reminderInput(value: string | null) {
  if (!value) return "";
  // Moscow's current UTC+03 offset, independent of the browser timezone.
  return new Date(new Date(value).getTime() + 3 * 60 * 60 * 1000)
    .toISOString()
    .slice(0, 16);
}
export function RetentionPanel({
  order,
  request,
  folder,
  op,
}: {
  order: Models["OrderRead"];
  request: Models["DeletionRead"] | null;
  folder: Models["FolderRead"] | null;
  op: Operation;
}) {
  const [confirming, setConfirming] = useState(false);
  if (!request)
    return (
      <Card title="Удаление материалов" className="retention-card">
        <p>
          Запрос на удаление пока не сформирован. Завершение заказа и удаление
          материалов — отдельные процессы.
        </p>
      </Card>
    );
  const performed = request.status === "performed" || !!folder?.deleted_at;
  const started = !!folder?.deletion_started_at;
  return (
    <Card title="Удаление материалов" className="retention-card">
      <p>
        <span className={`badge ${request.status}`}>
          {deletions[request.status]}
        </span>
      </p>
      <dl className="facts">
        <dt>Основание</dt>
        <dd>
          {request.reason === "early_permission"
            ? "Досрочное разрешение заказчика"
            : request.reason === "order_cancelled"
              ? "Отмена заказа"
              : "Истечение срока хранения"}
        </dd>
        <dt>Срок</dt>
        <dd>{date(request.due_at)}</dd>
        <dt>Досрочное разрешение</dt>
        <dd>{date(request.early_authorized_at)}</dd>
        <dt>Следующее напоминание</dt>
        <dd>{date(request.deferred_until)}</dd>
        <dt>Решение подтверждено</dt>
        <dd>{date(request.confirmed_at)}</dd>
        <dt>Удаление проверено</dt>
        <dd>{date(request.performed_at)}</dd>
      </dl>
      {request.admin_note && <p>Причина отсрочки: {request.admin_note}</p>}
      <p>
        Подписанное соглашение и журнал сохраняются. Удаление папки
        окончательное, без корзины.
      </p>
      {!performed && (
        <>
          {!started && (
            <>
              <Form
                key={request.deferred_until ?? "new-reminder"}
                method="post"
                busy={op.busy}
                onSubmit={(event) => {
                  const data = formData(event);
                  void op.run(
                    (api) =>
                      api.POST(
                        "/api/admin/orders/{order_id}/deletion-request/defer",
                        {
                          params: { path: { order_id: order.id } },
                          body: {
                            deletion_request_id: request.id,
                            deferred_until: moscowDate(
                              text(data, "deferred_until"),
                            ),
                            note: text(data, "note"),
                          },
                        },
                      ),
                    "Дата следующего напоминания сохранена.",
                  );
                }}
              >
                <Field
                  label="Следующее напоминание (МСК)"
                  name="deferred_until"
                  type="datetime-local"
                  defaultValue={reminderInput(request.deferred_until)}
                  required
                />
                <label className="field">
                  Причина отсрочки
                  <textarea
                    name="note"
                    rows={3}
                    required
                    maxLength={2000}
                    defaultValue={request.admin_note ?? ""}
                  />
                </label>
                <p>
                  Дата меняет только напоминание. Удалить материалы можно
                  отдельным явным действием и до этой даты.
                </p>
                <Button type="submit">
                  {request.deferred_until
                    ? "Изменить дату напоминания"
                    : "Отложить"}
                </Button>
              </Form>
            </>
          )}
          {folder && (
            <p>
              <Button
                className="danger"
                disabled={op.busy}
                onClick={() => setConfirming(true)}
              >
                {started
                  ? "Проверить / повторить операцию удаления"
                  : "Удалить материалы"}
              </Button>
            </p>
          )}
          {started && (
            <Notice tone="warning">
              Операция уже начата. Отсрочка недоступна. Проверяйте её результат
              отдельным действием; незавершённая операция ещё не означает
              удаления.
            </Notice>
          )}
        </>
      )}
      <Modal
        busy={op.busy}
        open={!!confirming}
        title="Удалить материалы"
        onClose={() => {
          if (!op.busy) setConfirming(false);
        }}
      >
        {confirming && op.notice?.error && (
          <Notice error>{op.notice.text}</Notice>
        )}
        <p>
          Заказ № {order.number}. Запрос {request.id}.
        </p>
        <p className="break-word">
          Папка: {folder?.disk_path ?? "не привязана"}
        </p>
        <p>
          Это действие подтверждает решение и запускает окончательное удаление
          папки без корзины. Подписанное соглашение и история заказа
          сохраняются.
        </p>
        <Form
          key={String(confirming)}
          busy={op.busy}
          method="post"
          onSubmit={(event) => {
            const data = formData(event);
            if (!confirming) return;
            void op.run(
              async (api) => {
                await api.POST("/api/admin/orders/{order_id}/folder/delete", {
                  params: { path: { order_id: order.id } },
                  body: {
                    deletion_request_id: request.id,
                    confirm: true,
                    permanent_deletion_verified:
                      data.get("permanent_deletion_verified") === "on",
                  },
                });
                setConfirming(false);
              },
              "Запрос обработан. Проверьте состояние удаления ниже; операция может ещё выполняться.",
              "Удаление не подтверждено. Проверьте состояние операции перед повтором.",
            );
          }}
        >
          <Check name="confirm">
            Подтверждаю запуск или проверку окончательного удаления именно этой
            папки
          </Check>
          {started && !folder?.deletion_operation_id && (
            <Check name="permanent_deletion_verified" required={false}>
              После потери ответа я лично проверил именно окончательное удаление
              этой папки в интерфейсе Яндекса (не перемещение и не корзину)
            </Check>
          )}
          <Button className="danger" type="submit">
            Подтвердить операцию удаления
          </Button>
        </Form>
      </Modal>
    </Card>
  );
}
