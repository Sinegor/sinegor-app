import { Link, Outlet, useLocation } from "react-router";
import { Brand } from "../components/brand";
import { LabArt } from "../components/lab-art";
import { MobileNavigation } from "../components/mobile-navigation";
export default function PublicLayout() {
  const auth = useLocation().pathname.startsWith("/auth/");
  const links = (
    <>
      <Link to="/auth/login">Вход заказчика</Link>
      <Link to="/auth/admin">Вход администратора</Link>
    </>
  );
  return (
    <>
      <header className="site-header">
        <Brand />
        <nav
          className="desktop-navigation public-navigation"
          aria-label="Основная навигация"
        >
          {links}
        </nav>
        <MobileNavigation title="Вход в SINEGOR LAB" label="Открыть входы">
          {links}
        </MobileNavigation>
      </header>
      <main id="main" className={`container${auth ? " auth-main" : ""}`}>
        {auth && (
          <div className="auth-art">
            <LabArt />
          </div>
        )}
        <Outlet />
      </main>
      <footer>Анализ и техническая подготовка документов</footer>
    </>
  );
}
