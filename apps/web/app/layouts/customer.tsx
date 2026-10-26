import { Link, Outlet, redirect, useLoaderData } from "react-router";
import { customerLoad, value } from "../lib/customer/api";
import { useOperation } from "../components/admin/common";
import { Feedback } from "../components/customer/common";
import { Button } from "../components/ui";
import { Brand } from "../components/brand";
import { MobileNavigation } from "../components/mobile-navigation";
import { usePrivateDocument } from "../lib/private-document";
export {
  CustomerErrorBoundary as ErrorBoundary,
  CustomerLoading as HydrateFallback,
} from "../components/customer/common";
export const headers = () => ({
  "Cache-Control": "no-store",
  "Referrer-Policy": "no-referrer",
  "X-Robots-Tag": "noindex, nofollow",
});
export async function clientLoader() {
  return customerLoad(async (api) => {
    const principal = await value(api.GET("/api/auth/session"));
    if (principal.role !== "customer") throw redirect("/auth/login");
    return principal;
  });
}
clientLoader.hydrate = true as const;
export const shouldRevalidate = () => true;
export default function CustomerLayout() {
  usePrivateDocument();
  const principal = useLoaderData<typeof clientLoader>();
  const op = useOperation("/auth/login");
  const logout = (
    <Button
      variant="text"
      disabled={op.busy}
      onClick={() =>
        op.run(async (api) => {
          await api.POST("/api/auth/logout");
          window.location.assign("/auth/login");
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
        <nav
          className="desktop-navigation"
          aria-label="Навигация личного кабинета"
        >
          <Link to="/customer/orders">Мои заказы</Link>
        </nav>
        <div className="desktop-navigation account-actions">
          <span className="break-word">{principal.email}</span>
          {logout}
        </div>
        <MobileNavigation title="Личный кабинет" label="Открыть меню кабинета">
          <p className="menu-account break-word">{principal.email}</p>
          <Link to="/customer/orders">Мои заказы</Link>
          {logout}
          <Feedback op={op} />
        </MobileNavigation>
      </header>
      <main id="main" className="container customer-main">
        <Feedback op={op} />
        <Outlet />
      </main>
    </>
  );
}
