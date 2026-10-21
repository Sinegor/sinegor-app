import {
  Form as SearchForm,
  Link,
  useLoaderData,
  type ClientLoaderFunctionArgs,
} from "react-router";
import {
  adminLoad,
  value,
  offset,
  PAGE_SIZE,
  type Models,
} from "../../lib/admin/api";
import { statuses } from "../../lib/admin/labels";
import {
  OrdersTable,
  Pagination,
  SelectField,
} from "../../components/admin/common";
import { Button, Field } from "../../components/ui";
export { AdminErrorBoundary as ErrorBoundary } from "../../components/admin/common";
export const meta = () => [{ title: "Заказы — SINEGOR" }];
export function clientLoader({ request }: ClientLoaderFunctionArgs) {
  const url = new URL(request.url),
    start = offset(url);
  const raw = url.searchParams.get("status") ?? "",
    customerId = url.searchParams.get("customer_id") ?? "";
  const status = Object.hasOwn(statuses, raw)
    ? (raw as Models["OrderStatus"])
    : undefined;
  return adminLoad(async (api) => ({
    start,
    status,
    customerId,
    rows: await value(
      api.GET("/api/admin/orders", {
        params: {
          query: {
            status,
            customer_id: customerId || undefined,
            offset: start,
            limit: PAGE_SIZE,
          },
        },
        signal: request.signal,
      }),
    ),
  }));
}
export default function Orders() {
  const { rows, status, customerId, start } =
    useLoaderData<typeof clientLoader>();
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">Заказы</p>
          <h1>Работа и результаты</h1>
        </div>
        <Link className="button-link" to="/admin/orders/new">
          Создать заказ
        </Link>
      </div>
      <SearchForm className="filter-bar" method="get">
        <SelectField
          key={status ?? "all"}
          label="Статус"
          name="status"
          value={status ?? ""}
        >
          <option value="">Все статусы</option>
          {Object.entries(statuses).map(([id, name]) => (
            <option key={id} value={id}>
              {name}
            </option>
          ))}
        </SelectField>
        <Field
          label="UUID заказчика (необязательно)"
          name="customer_id"
          defaultValue={customerId}
        />
        <Button type="submit">Применить</Button>
        <Link to="/admin/orders">Сбросить</Link>
      </SearchForm>
      <OrdersTable rows={rows} />
      <Pagination count={rows.length} start={start} />
    </>
  );
}
