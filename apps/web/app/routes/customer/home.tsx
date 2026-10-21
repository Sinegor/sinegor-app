import {
  Link,
  useLoaderData,
  useRevalidator,
  type ClientLoaderFunctionArgs,
} from "react-router";
import { customerLoad, value } from "../../lib/customer/api";
import { date, money, services, statuses } from "../../lib/admin/labels";
import { Button, Card } from "../../components/ui";
export { CustomerErrorBoundary as ErrorBoundary } from "../../components/customer/common";
export const meta = () => [{ title: "Мои заказы — SINEGOR" }];
export function clientLoader({ request }: ClientLoaderFunctionArgs) {
  return customerLoad((api) =>
    value(api.GET("/api/customer/orders", { signal: request.signal })),
  );
}
export default function CustomerOrders() {
  const orders = useLoaderData<typeof clientLoader>(),
    revalidator = useRevalidator();
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">Личный кабинет</p>
          <h1>Мои заказы</h1>
        </div>
        <Button
          disabled={revalidator.state !== "idle"}
          onClick={() => revalidator.revalidate()}
        >
          Обновить список
        </Button>
      </div>
      <p>Условия, соглашение, материалы и результат — в карточке заказа.</p>
      {orders.length ? (
        <div className="customer-orders">
          {orders.map((order) => (
            <Card key={order.id} title={`Заказ № ${order.number}`}>
              <span className={`badge ${order.status}`}>
                {statuses[order.status]}
              </span>
              <p>{services[order.service_type]}</p>
              <dl className="facts">
                <dt>Создан</dt>
                <dd>{date(order.created_at)}</dd>
                <dt>Стоимость</dt>
                <dd>{money(order.agreed_price)}</dd>
              </dl>
              <Link className="button-link" to={`/customer/orders/${order.id}`}>
                Открыть заказ № {order.number}
              </Link>
            </Card>
          ))}
        </div>
      ) : (
        <Card title="Заказов пока нет">
          <p>
            Когда исполнитель оформит заказ на ваш email, он появится здесь.
          </p>
        </Card>
      )}
    </>
  );
}
