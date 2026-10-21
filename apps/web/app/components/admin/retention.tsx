import { useState } from "react";
import type { Models } from "../../lib/admin/api";
import { date, deletions } from "../../lib/admin/labels";
import { Button, Card, Form, Field, Modal, Notice } from "../ui";
import { Check, formData, text, type Operation } from "./common";
export function moscowDate(value: string) {
  return new Date(`${value}+03:00`).toISOString();
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
  const [confirming, setConfirming] = useState<"decision" | "delete" | null>(
    null,
  );
  if (!request)
    return (
      <Card title="Удаление материалов">
        <p>
          Запрос на удаление пока не сформирован. Завершение заказа и удаление
          материалов — отдельные процессы.
        </p>
      </Card>
    );
  const performed = request.status === "performed" || !!folder?.deleted_at;
  const started = !!folder?.deletion_started_at;
  return (
    <Card title="Удаление материалов">
      <p>
        <span className="badge">{deletions[request.status]}</span>
      </p>
      <dl className="facts">
        <dt>Основание</dt>
        <dd>
          {request.reason === "early_permission"
            ? "Досрочное разрешение заказчика"
            : "Истечение срока хранения"}
        </dd>
        <dt>Срок</dt>
        <dd>{date(request.due_at)}</dd>
        <dt>Досрочное разрешение</dt>
        <dd>{date(request.early_authorized_at)}</dd>
        <dt>Отсрочка до</dt>
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
              <Button
                disabled={op.busy}
                onClick={() => setConfirming("decision")}
              >
                Подтвердить решение об удалении
              </Button>
              <Form
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
                    "Удаление отложено.",
                  );
                }}
              >
                <Field
                  label="Отложить до (МСК)"
                  name="deferred_until"
                  type="datetime-local"
                  required
                />
                <label className="field">
                  Причина отсрочки
                  <textarea name="note" rows={3} required maxLength={2000} />
                </label>
                <Button type="submit">Отложить удаление</Button>
              </Form>
            </>
          )}
          {["confirmed", "error"].includes(request.status) && folder && (
            <p>
              <Button
                className="danger"
                disabled={op.busy}
                onClick={() => setConfirming("delete")}
              >
                {started
                  ? "Проверить / повторить операцию удаления"
                  : "Удалить папку окончательно"}
              </Button>
            </p>
          )}
          {started && (
            <Notice>
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
        title={
          confirming === "decision"
            ? "Подтвердить решение?"
            : "Окончательное удаление папки"
        }
        onClose={() => {
          if (!op.busy) setConfirming(null);
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
        <Form
          key={confirming}
          busy={op.busy}
          method="post"
          onSubmit={(event) => {
            const data = formData(event),
              mode = confirming;
            if (!mode) return;
            void op.run(
              async (api) => {
                if (mode === "decision")
                  await api.POST(
                    "/api/admin/orders/{order_id}/deletion-request/confirm",
                    {
                      params: { path: { order_id: order.id } },
                      body: { deletion_request_id: request.id, confirm: true },
                    },
                  );
                else
                  await api.POST("/api/admin/orders/{order_id}/folder/delete", {
                    params: { path: { order_id: order.id } },
                    body: {
                      deletion_request_id: request.id,
                      confirm: true,
                      permanent_deletion_verified:
                        data.get("permanent_deletion_verified") === "on",
                    },
                  });
                setConfirming(null);
              },
              mode === "decision"
                ? "Решение сохранено. Для удаления требуется отдельное действие."
                : "Запрос обработан. Проверьте состояние удаления ниже; операция может ещё выполняться.",
              mode === "delete"
                ? "Удаление не подтверждено. Проверьте состояние операции перед повтором."
                : undefined,
            );
          }}
        >
          <Check name="confirm">
            {confirming === "decision"
              ? "Я проверил обращения заказчика и подтверждаю решение. Это действие пока не удаляет файлы."
              : "Подтверждаю запуск или проверку окончательного удаления именно этой папки"}
          </Check>
          {confirming === "delete" &&
            started &&
            !folder?.deletion_operation_id && (
              <Check name="permanent_deletion_verified" required={false}>
                После потери ответа я лично проверил именно окончательное
                удаление этой папки в интерфейсе Яндекса (не перемещение и не
                корзину)
              </Check>
            )}
          <Button
            className={confirming === "delete" ? "danger" : ""}
            type="submit"
          >
            {confirming === "decision"
              ? "Подтвердить решение"
              : "Подтвердить операцию удаления"}
          </Button>
        </Form>
      </Modal>
    </Card>
  );
}
