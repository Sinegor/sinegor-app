import { Link, Outlet } from "react-router";
export const headers = () => ({
  "Cache-Control": "no-store",
  "Referrer-Policy": "no-referrer",
  "X-Robots-Tag": "noindex, nofollow",
});
export default function CustomerLayout() {
  return (
    <>
      <header>
        <Link className="brand" to="/">
          SINEGOR
        </Link>
        <span>Личный кабинет</span>
      </header>
      <main id="main" className="container">
        <Outlet />
      </main>
    </>
  );
}
