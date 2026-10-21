import { Link, NavLink, Outlet, redirect } from "react-router";
import { adminLoad, value } from "../lib/admin/api";
import { Button } from "../components/ui";
import { Feedback, useOperation } from "../components/admin/common";
export { headers } from "./customer";
export {
  AdminErrorBoundary as ErrorBoundary,
  Loading as HydrateFallback,
} from "../components/admin/common";
export async function clientLoader() {
  return adminLoad(async (api) => {
    const principal = await value(api.GET("/api/auth/session"));
    if (principal.role !== "admin") throw redirect("/auth/admin");
    return principal;
  });
}
clientLoader.hydrate = true as const;
export const shouldRevalidate = () => true;
export default function AdminLayout() {
  const op = useOperation();
  return (
    <>
      <header>
        <Link className="brand" to="/">
          SINEGOR
        </Link>
        <span>Административная панель</span>
        <Button
          disabled={op.busy}
          onClick={() =>
            op.run(async (api) => {
              await api.POST("/api/auth/logout");
              window.location.assign("/auth/admin");
            }, "")
          }
        >
          Выйти
        </Button>
      </header>
      <div className="admin-shell">
        <aside>
          <nav aria-label="Разделы администратора">
            <NavLink to="/admin/customers">Заказчики</NavLink>
            <NavLink to="/admin/orders">Заказы</NavLink>
          </nav>
          <p>Сроки и даты показаны по московскому времени.</p>
        </aside>
        <main id="main" className="admin-main">
          <Feedback op={op} />
          <Outlet />
        </main>
      </div>
    </>
  );
}
