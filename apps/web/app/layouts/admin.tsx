import { NavLink, Outlet, redirect } from "react-router";
import { adminLoad, value } from "../lib/admin/api";
import { Button } from "../components/ui";
import { Feedback, useOperation } from "../components/admin/common";
import { DeliveryWarning } from "../components/admin/delivery-warning";
import { Brand } from "../components/brand";
import { MobileNavigation } from "../components/mobile-navigation";
import { usePrivateDocument } from "../lib/private-document";
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
  usePrivateDocument();
  const op = useOperation();
  const links = (
    <>
      <NavLink to="/admin/customers">Заказчики</NavLink>
      <NavLink to="/admin/orders">Заказы</NavLink>
      <NavLink to="/admin/consultations">Контроль отправки уведомлений</NavLink>
      <NavLink to="/admin/security-events">События безопасности</NavLink>
      <NavLink to="/admin/destructions">Реестр уничтожения</NavLink>
    </>
  );
  const logout = (
    <Button
      variant="text"
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
  );
  return (
    <>
      <header className="site-header">
        <Brand compact />
        <span className="desktop-navigation header-caption">
          Административная панель
        </span>
        <div className="desktop-navigation">{logout}</div>
        <MobileNavigation title="Разделы" label="Открыть разделы">
          {links}
          {logout}
          <Feedback op={op} />
        </MobileNavigation>
      </header>
      <div className="admin-shell">
        <aside className="desktop-sidebar">
          <nav aria-label="Разделы администратора">{links}</nav>
          <p>
            Даты показаны по московскому времени, если в разделе не указано
            иное.
          </p>
        </aside>
        <main id="main" className="admin-main">
          <Feedback op={op} />
          <DeliveryWarning />
          <Outlet />
        </main>
      </div>
    </>
  );
}
