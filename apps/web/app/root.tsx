import {
  Links,
  Meta,
  Outlet,
  Scripts,
  ScrollRestoration,
  isRouteErrorResponse,
  useNavigation,
  useRouteError,
  Link,
} from "react-router";
import type { ReactNode } from "react";
import "./styles/app.css";
import manropeFont from "../assets/fonts/Manrope-variable.ttf";

export function Layout({ children }: { children: ReactNode }) {
  return (
    <html lang="ru">
      <head>
        <meta charSet="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <meta name="referrer" content="no-referrer" />
        <link
          rel="preload"
          href={manropeFont}
          as="font"
          type="font/ttf"
          crossOrigin="anonymous"
        />
        <Meta />
        <Links />
      </head>
      <body>
        <a className="skip-link" href="#main">
          Перейти к содержимому
        </a>
        {children}
        <ScrollRestoration />
        <Scripts />
      </body>
    </html>
  );
}
export default function App() {
  const navigation = useNavigation();
  return (
    <>
      {navigation.state !== "idle" && (
        <div className="loading" role="status">
          Загрузка…
        </div>
      )}
      <Outlet />
    </>
  );
}
export function ErrorBoundary() {
  const error = useRouteError();
  const missing = isRouteErrorResponse(error) && error.status === 404;
  return (
    <main id="main" className="container">
      <h1>{missing ? "Страница не найдена" : "Не удалось открыть страницу"}</h1>
      <p>
        {missing ? "Проверьте адрес страницы." : "Повторите попытку позже."}
      </p>
      <Link to="/">На главную</Link>
    </main>
  );
}
