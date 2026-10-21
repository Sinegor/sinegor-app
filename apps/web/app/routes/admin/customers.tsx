import {
  Form as SearchForm,
  Link,
  useLoaderData,
  useLocation,
  type ClientLoaderFunctionArgs,
} from "react-router";
import { adminLoad, value, offset, PAGE_SIZE } from "../../lib/admin/api";
import { Field, Button, Table } from "../../components/ui";
import { Pagination } from "../../components/admin/common";
export { AdminErrorBoundary as ErrorBoundary } from "../../components/admin/common";
export const meta = () => [{ title: "Заказчики — SINEGOR" }];
export function clientLoader({ request }: ClientLoaderFunctionArgs) {
  const url = new URL(request.url),
    start = offset(url),
    q = url.searchParams.get("q") ?? "";
  return adminLoad(async (api) => ({
    start,
    q,
    rows: await value(
      api.GET("/api/admin/customers", {
        params: { query: { q, offset: start, limit: PAGE_SIZE } },
        signal: request.signal,
      }),
    ),
  }));
}
export default function Customers() {
  const { rows, start, q } = useLoaderData<typeof clientLoader>();
  const location = useLocation();
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">Заказчики</p>
          <h1>Контакты и заказы</h1>
        </div>
        <Link className="button-link" to="/admin/customers/new">
          Создать заказчика
        </Link>
      </div>
      <SearchForm className="filter-bar" method="get">
        <Field
          key={location.key}
          label="Поиск по имени, email или телефону"
          name="q"
          defaultValue={q}
          maxLength={320}
        />
        <Button type="submit">Найти</Button>
        <Link to="/admin/customers">Сбросить</Link>
      </SearchForm>
      <Table
        caption="Заказчики"
        columns={["Заказчик", "Email", "Телефон"]}
        rows={rows.map((row) => [
          <Link to={`/admin/customers/${row.id}`}>
            {row.display_name || row.email}
          </Link>,
          row.email,
          row.phone || "—",
        ])}
      />
      <Pagination count={rows.length} start={start} />
    </>
  );
}
