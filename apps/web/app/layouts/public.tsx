import {
  Link,
  NavLink,
  Outlet,
  useLocation,
  type ShouldRevalidateFunction,
} from "react-router";
import { Brand } from "../components/brand";
import { LabArt } from "../components/lab-art";
import { MobileNavigation } from "../components/mobile-navigation";
import type { Route } from "./+types/public";
import {
  publicOrigin,
  publicRedirect,
  documentUrl,
} from "../lib/public-url.server";
import { linkSectionForPath } from "../lib/public-url";
import { loadPageLinks } from "../lib/page-links.server";
import { PageLinks } from "../components/page-links";
import { PublicFooter } from "../components/public-footer";
import {
  AnalyticsConsent,
  PublicAnalytics,
} from "../components/public-analytics";
import { analyticsConfig } from "../lib/analytics.server";

export const middleware: Route.MiddlewareFunction[] = [
  async ({ request }, next) => {
    const response = publicRedirect(request);
    if (response) throw response;
    return next();
  },
];

export async function loader({ request }: Route.LoaderArgs) {
  const section = linkSectionForPath(documentUrl(request).pathname);
  return {
    analytics: analyticsConfig(),
    publicOrigin: publicOrigin(request),
    year: Number(
      new Intl.DateTimeFormat("en", {
        year: "numeric",
        timeZone: "Europe/Moscow",
      }).format(new Date()),
    ),
    pageLinks: section ? await loadPageLinks(section) : [],
  };
}

export const shouldRevalidate: ShouldRevalidateFunction = ({
  currentUrl,
  nextUrl,
  defaultShouldRevalidate,
}) =>
  defaultShouldRevalidate ||
  linkSectionForPath(currentUrl.pathname) !==
    linkSectionForPath(nextUrl.pathname);

export default function PublicLayout({ loaderData }: Route.ComponentProps) {
  const auth = useLocation().pathname.startsWith("/auth/");
  const links = (
    <>
      {!auth && (
        <>
          <NavLink to="/services/ai-analysis">ИИ-анализ</NavLink>
          <NavLink to="/services/technical">Обработка</NavLink>
          <NavLink to="/about">Обо мне</NavLink>
          <NavLink to="/publications">Публикации</NavLink>
          <NavLink to="/documents">Документы</NavLink>
        </>
      )}
      <Link to="/auth/login">Вход заказчика</Link>
      <Link to="/auth/admin">Вход администратора</Link>
    </>
  );
  return (
    <PublicAnalytics counterId={loaderData.analytics?.counterId}>
      <div className="public-shell">
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
          <AnalyticsConsent />
          {auth && (
            <div className="auth-art">
              <LabArt />
            </div>
          )}
          <Outlet />
          <PageLinks links={loaderData.pageLinks} />
        </main>
        <PublicFooter year={loaderData.year} />
      </div>
    </PublicAnalytics>
  );
}
