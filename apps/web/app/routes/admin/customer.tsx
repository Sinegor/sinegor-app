import {
  Link,
  useLoaderData,
  useSearchParams,
  type ClientLoaderFunctionArgs,
} from "react-router";
import {
  adminLoad,
  value,
  offset,
  PAGE_SIZE,
  type Models,
} from "../../lib/admin/api";
import { Card, Form, Field, Button, Notice } from "../../components/ui";
import {
  Feedback,
  useOperation,
  formData,
  text,
  OrdersTable,
  Pagination,
} from "../../components/admin/common";
export { AdminErrorBoundary as ErrorBoundary } from "../../components/admin/common";
export const meta = () => [{ title: "Карточка заказчика — SINEGOR" }];
export function clientLoader({ params, request }: ClientLoaderFunctionArgs) {
  const id = params.customerId!,
    start = offset(new URL(request.url));
  return adminLoad(async (api) => {
    const [customer, orders] = await Promise.all([
      value(
        api.GET("/api/admin/customers/{customer_id}", {
          params: { path: { customer_id: id } },
          signal: request.signal,
        }),
      ),
      value(
        api.GET("/api/admin/orders", {
          params: {
            query: { customer_id: id, limit: PAGE_SIZE, offset: start },
          },
          signal: request.signal,
        }),
      ),
    ]);
    return { customer, orders, start };
  });
}
export default function Customer() {
  const { customer, orders, start } = useLoaderData<typeof clientLoader>();
  const op = useOperation(),
    [params, setParams] = useSearchParams();
  return (
    <>
      <Link to="/admin/customers">← Заказчики</Link>
      <div className="page-heading">
        <h1>{customer.display_name || customer.email}</h1>
        <Link
          className="button-link"
          to={`/admin/orders/new?customer_id=${customer.id}`}
        >
          Создать заказ
        </Link>
      </div>
      <Feedback op={op} />
      {params.get("invitation") === "failed" && (
        <Notice error>
          Заказчик создан, но приглашение не отправлено. Повторите приглашение
          кнопкой ниже; создавать карточку заново не нужно.
        </Notice>
      )}
      <Card title="Карточка заказчика">
        <Form
          key={`${customer.email}:${customer.display_name}:${customer.phone}`}
          busy={op.busy}
          method="post"
          onSubmit={(event) => {
            const data = formData(event);
            const changes: Models["CustomerUpdate"] = {};
            if (data.get("email") !== customer.email)
              changes.email = text(data, "email");
            if (data.get("display_name") !== (customer.display_name ?? ""))
              changes.display_name = text(data, "display_name") || null;
            if (data.get("phone") !== (customer.phone ?? ""))
              changes.phone = text(data, "phone") || null;
            void op.run(
              (api) =>
                value(
                  api.PATCH("/api/admin/customers/{customer_id}", {
                    params: { path: { customer_id: customer.id } },
                    body: changes,
                  }),
                ),
              "Карточка сохранена.",
            );
          }}
        >
          <Field
            label="Email"
            name="email"
            type="email"
            required
            maxLength={320}
            defaultValue={customer.email}
          />
          <Field
            label="Имя или наименование"
            name="display_name"
            maxLength={255}
            defaultValue={customer.display_name ?? ""}
          />
          <Field
            label="Телефон"
            name="phone"
            type="tel"
            maxLength={50}
            defaultValue={customer.phone ?? ""}
          />
          <p>
            При смене email прежние ссылки и сеансы отзываются. Новое
            приглашение отправляется отдельно.
          </p>
          <Button type="submit">Сохранить карточку</Button>
        </Form>
        <p>
          <Button
            disabled={op.busy}
            onClick={() =>
              op.run(async (api) => {
                await api.POST("/api/admin/customers/{customer_id}/invite", {
                  params: { path: { customer_id: customer.id } },
                });
                if (params.has("invitation")) {
                  const next = new URLSearchParams(params);
                  next.delete("invitation");
                  setParams(next, { replace: true });
                }
              }, "Приглашение передано почтовому сервису.")
            }
          >
            Повторить приглашение
          </Button>
        </p>
      </Card>
      <Card title="История заказов">
        <OrdersTable rows={orders} />
        <Pagination count={orders.length} start={start} />
      </Card>
    </>
  );
}
