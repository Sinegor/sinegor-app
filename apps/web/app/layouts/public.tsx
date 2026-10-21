import { Link, Outlet } from "react-router";
export default function PublicLayout() {
  return (
    <>
      <header>
        <Link className="brand" to="/">
          SINEGOR
        </Link>
        <nav aria-label="Основная навигация">
          <Link to="/customer">Личный кабинет</Link>
        </nav>
      </header>
      <main id="main" className="container">
        <Outlet />
      </main>
      <footer>Анализ и техническая подготовка документов</footer>
    </>
  );
}
