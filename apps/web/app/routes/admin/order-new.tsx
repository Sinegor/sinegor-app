import {
  Link,
  useLoaderData,
  useNavigate,
  type ClientLoaderFunctionArgs,
} from "react-router";
import { adminLoad, value } from "../../lib/admin/api";
import { Card, Form, Button } from "../../components/ui";
import {
  Feedback,
  useOperation,
  formData,
  text,
} from "../../components/admin/common";
import { CustomerCombobox } from "../../components/admin/customer-combobox";
import { TermsFields, terms } from "../../components/admin/terms";
export { AdminErrorBoundary as ErrorBoundary } from "../../components/admin/common";
export function clientLoader({ request }: ClientLoaderFunctionArgs) {
  const selected = new URL(request.url).searchParams.get("customer_id");
  return adminLoad(async (api) => ({
    customer: selected
      ? await value(
          api.GET("/api/admin/customers/{customer_id}", {
            params: { path: { customer_id: selected } },
            signal: request.signal,
          }),
        )
      : null,
  }));
}
export const meta = () => [{ title: "Новый заказ — SINEGOR LAB" }];
export default function OrderNew() {
  const { customer } = useLoaderData<typeof clientLoader>();
  const op = useOperation(),
    navigate = useNavigate();
  return (
    <>
      <Link to="/admin/orders">← Заказы</Link>
      <h1>Новый заказ</h1>
      <Feedback op={op} />
      <Card title="Заказчик и условия">
        <Form
          method="post"
          busy={op.busy}
          onSubmit={(event) => {
            const data = formData(event);
            void op.run(async (api) => {
              const order = await value(
                api.POST("/api/admin/orders", {
                  body: {
                    ...terms(data),
                    customer_id: text(data, "customer_id"),
                  },
                }),
              );
              await navigate(`/admin/orders/${order.id}`);
            }, "");
          }}
        >
          <CustomerCombobox initial={customer} />
          <TermsFields />
          <Button type="submit">Создать заказ</Button>
        </Form>
      </Card>
    </>
  );
}
