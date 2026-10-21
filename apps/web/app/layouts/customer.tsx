import { Link, Outlet, redirect, useLoaderData } from "react-router";
import { customerLoad, value } from "../lib/customer/api";
import { useOperation } from "../components/admin/common";
import { Feedback } from "../components/customer/common";
import { Button } from "../components/ui";
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
  const principal = useLoaderData<typeof clientLoader>();
  const op = useOperation("/auth/login");
  return (
    <>
      <header>
        <Link className="brand" to="/">
          SINEGOR
        </Link>
        <nav aria-label="Навигация личного кабинета">
          <Link to="/customer/orders">Мои заказы</Link>
        </nav>
        <span className="break-word">{principal.email}</span>
        <Button
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
      </header>
      <main id="main" className="container customer-main">
        <Feedback op={op} />
        <Outlet />
      </main>
    </>
  );
}
