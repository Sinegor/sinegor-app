import {
  Form as SearchForm,
  Link,
  useLoaderData,
  useNavigate,
  type ClientLoaderFunctionArgs,
} from "react-router";
import { adminLoad, value } from "../../lib/admin/api";
import { Card, Form, Field, Button } from "../../components/ui";
import {
  Feedback,
  useOperation,
  formData,
  text,
  SelectField,
} from "../../components/admin/common";
import { TermsFields, terms } from "../../components/admin/terms";
export { AdminErrorBoundary as ErrorBoundary } from "../../components/admin/common";
export function clientLoader({ request }: ClientLoaderFunctionArgs) {
  const url = new URL(request.url),
    selected = url.searchParams.get("customer_id") ?? "",
    q = url.searchParams.get("q") ?? "";
  return adminLoad(async (api) => {
    const rows = await value(
      api.GET("/api/admin/customers", {
        params: { query: { q, limit: 100 } },
        signal: request.signal,
      }),
    );
    if (selected && !rows.some((row) => row.id === selected))
      rows.unshift(
        await value(
          api.GET("/api/admin/customers/{customer_id}", {
            params: { path: { customer_id: selected } },
            signal: request.signal,
          }),
        ),
      );
    return { rows, selected, q };
  });
}
export const meta = () => [{ title: "Новый заказ — SINEGOR" }];
export default function OrderNew() {
  const { rows, selected, q } = useLoaderData<typeof clientLoader>();
  const op = useOperation(),
    navigate = useNavigate();
  return (
    <>
      <Link to="/admin/orders">← Заказы</Link>
      <h1>Новый заказ</h1>
      <Feedback op={op} />
      <Card title="Заказчик и условия">
        <SearchForm method="get" className="filter-bar">
          <Field
            label="Найти заказчика"
            name="q"
            maxLength={320}
            defaultValue={q}
          />
          <Button type="submit">Найти</Button>
        </SearchForm>
        <p>
          Показаны первые 100 совпадений. Уточните поиск, если нужного заказчика
          нет.
        </p>
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
          <SelectField
            key={`${selected}:${q}`}
            label="Заказчик"
            name="customer_id"
            value={selected}
            required
          >
            <option value="">Выберите заказчика</option>
            {rows.map((row) => (
              <option key={row.id} value={row.id}>
                {row.display_name ? `${row.display_name} · ` : ""}
                {row.email}
              </option>
            ))}
          </SelectField>
          <TermsFields />
          <Button type="submit">Создать заказ</Button>
        </Form>
      </Card>
    </>
  );
}
