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
import { Brand } from "./components/brand";
import { LabArt } from "./components/lab-art";
import { LoadingStatus } from "./components/ui";

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
        <LoadingStatus className="loading">Загрузка…</LoadingStatus>
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
      <Brand compact />
      <div className="error-state">
        <LabArt compact />
        <p className="eyebrow">{missing ? "Ошибка 404" : "Ошибка загрузки"}</p>
        <h1>
          {missing ? "Страница не найдена" : "Не удалось открыть страницу"}
        </h1>
        <p>
          {missing ? "Проверьте адрес страницы." : "Повторите попытку позже."}
        </p>
        <Link className="button-link" to="/">
          На главную
        </Link>
      </div>
    </main>
  );
}
