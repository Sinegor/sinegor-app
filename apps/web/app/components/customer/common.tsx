import { Link, useRouteError } from "react-router";
import { ApiError } from "../../lib/api/client";
import { message } from "../../lib/admin/api";
import { Notice, Button } from "../ui";
import { PageLoading } from "../page-loading";
export { Feedback, Check, formData, text } from "../admin/common";
export function CustomerLoading() {
  return <PageLoading>Загрузка личного кабинета…</PageLoading>;
}
export function CustomerErrorBoundary() {
  const error = useRouteError();
  return (
    <section>
      <h1>Не удалось открыть заказ</h1>
      <Notice error>
        {error instanceof ApiError && error.status === 404
          ? "Заказ не найден или недоступен."
          : message(error)}
      </Notice>
      <div className="actions">
        <Link to="/customer/orders">Мои заказы</Link>
        <Link to="/auth/login">Войти по новой ссылке</Link>
        <Button onClick={() => window.location.reload()}>
          Повторить загрузку
        </Button>
      </div>
    </section>
  );
}
