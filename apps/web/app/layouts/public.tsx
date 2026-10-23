import { Link, NavLink, Outlet, useLocation } from "react-router";
import { Brand } from "../components/brand";
import { LabArt } from "../components/lab-art";
import { MobileNavigation } from "../components/mobile-navigation";
export default function PublicLayout() {
  const auth = useLocation().pathname.startsWith("/auth/");
  const links = (
    <>
      {!auth && (
        <>
          <NavLink to="/services/ai-analysis">ИИ-анализ</NavLink>
          <NavLink to="/services/technical">Обработка</NavLink>
          <NavLink to="/about">Обо мне</NavLink>
          <NavLink to="/publications">Публикации</NavLink>
          <NavLink to="/contacts">Контакты</NavLink>
        </>
      )}
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
        <MobileNavigation
          title={auth ? "Вход в SINEGOR LAB" : "Навигация SINEGOR LAB"}
          label={auth ? "Открыть входы" : "Открыть меню"}
        >
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
