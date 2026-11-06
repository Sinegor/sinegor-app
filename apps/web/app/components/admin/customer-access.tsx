import { useId } from "react";
import { Button, Card, Form } from "../ui";
import { formData, text, type useOperation } from "./common";
import { value, type Models } from "../../lib/admin/api";
import { date } from "../../lib/admin/labels";

export function CustomerAccess({
  customer,
  op,
}: {
  customer: Models["CustomerRead"];
  op: ReturnType<typeof useOperation>;
}) {
  const id = useId();
  return (
    <Card title="Доступ к личному кабинету">
      <p>
        <strong>
          {customer.blocked_at ? "Доступ заблокирован" : "Доступ разрешён"}
        </strong>
      </p>
      <p>
        Блокировка действует только на вход и работу в личном кабинете,
        бессрочно до решения администратора. Заказы, соглашения и материалы
        сохраняются. Права на папки Яндекс Диска и аккаунты Strapi не меняются.
      </p>
      {customer.blocked_at ? (
        <>
          <dl>
            <dt>Заблокирован</dt>
            <dd>{date(customer.blocked_at)}</dd>
            <dt>Причина для заказчика</dt>
            <dd className="access-text">{customer.block_reason}</dd>
            <dt>Внутренний комментарий</dt>
            <dd className="access-text">
              {customer.block_comment || "Не указан"}
            </dd>
          </dl>
          <p>
            После разблокирования прежние ссылки и сеансы останутся
            недействительными. Заказчику потребуется новая одноразовая ссылка.
            Причина и внутренний комментарий будут удалены из карточки.
          </p>
          <Button
            disabled={op.busy}
            onClick={() =>
              void op.run(
                (api) =>
                  value(
                    api.POST("/api/admin/customers/{customer_id}/unblock", {
                      params: { path: { customer_id: customer.id } },
                    }),
                  ),
                "Доступ восстановлен. Уведомление поставлено в очередь.",
              )
            }
          >
            Разблокировать
          </Button>
        </>
      ) : (
        <Form
          busy={op.busy}
          method="post"
          onSubmit={(event) => {
            const data = formData(event);
            void op.run(
              (api) =>
                value(
                  api.POST("/api/admin/customers/{customer_id}/block", {
                    params: { path: { customer_id: customer.id } },
                    body: {
                      reason: text(data, "reason"),
                      internal_comment: text(data, "internal_comment") || null,
                    },
                  }),
                ),
              "Доступ заблокирован. Уведомление поставлено в очередь.",
            );
          }}
        >
          <div className="field">
            <label htmlFor={`${id}-reason`}>Причина для заказчика</label>
            <textarea
              id={`${id}-reason`}
              name="reason"
              required
              maxLength={2000}
              rows={3}
              aria-describedby={`${id}-hint`}
            />
            <p id={`${id}-hint`}>
              Эта причина будет отправлена заказчику по email. Все действующие
              сеансы, ссылки входа и приглашения будут отозваны.
            </p>
          </div>
          <div className="field">
            <label htmlFor={`${id}-comment`}>Внутренний комментарий</label>
            <textarea
              id={`${id}-comment`}
              name="internal_comment"
              maxLength={2000}
              rows={3}
              aria-describedby={`${id}-private`}
            />
            <p id={`${id}-private`}>
              Необязательно. Доступен только администратору; в письмо не
              включается.
            </p>
          </div>
          <Button type="submit">Заблокировать</Button>
        </Form>
      )}
    </Card>
  );
}
