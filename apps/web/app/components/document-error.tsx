import { isRouteErrorResponse, Link, useRouteError } from "react-router";

export function DocumentError() {
  const error = useRouteError();
  const missing = isRouteErrorResponse(error) && error.status === 404;
  return (
    <section className="public-page public-prose">
      <h1>
        {missing ? "Документ не найден" : "Документы временно недоступны"}
      </h1>
      <p>
        {missing
          ? "Проверьте адрес или выберите документ в каталоге."
          : "Не удалось загрузить документы. Повторите попытку позже."}
      </p>
      <Link to="/documents">Все документы</Link>
    </section>
  );
}
