import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useLocation, useMatches } from "react-router";
import { analyticsPath, type AnalyticsGoal } from "../lib/analytics";
import { startMetrika } from "../lib/metrika.client";
import {
  ANALYTICS_CONSENT_KEY,
  loadAnalyticsConsent,
  saveAnalyticsConsent,
  type AnalyticsConsent as Consent,
} from "../lib/analytics-consent";
import { Button, Modal } from "./ui";

const AnalyticsContext = createContext<
  ((goal: AnalyticsGoal, path: string) => void) | null
>(null);
const ConsentContext = createContext<{
  available: boolean;
  prompt: boolean;
  consent: Consent | null;
  open: boolean;
  setOpen: (open: boolean) => void;
  choose: (decision: Consent["decision"]) => void;
} | null>(null);

export function useAnalytics() {
  const record = useContext(AnalyticsContext);
  const location = useLocation();
  const path = analyticsPath(location.pathname, location.search);
  return (goal: AnalyticsGoal) => {
    if (path) record?.(goal, path);
  };
}

export function PublicAnalytics({
  counterId,
  children,
}: {
  counterId?: number;
  children: ReactNode;
}) {
  const location = useLocation();
  const leaf = useMatches().at(-1);
  const [consent, setConsent] = useState<Consent | null>(null);
  const [ready, setReady] = useState(false);
  const [open, setOpen] = useState(false);
  const publicPage =
    !!leaf?.id.startsWith("routes/public/") && leaf.data !== undefined;
  const allowed =
    !!counterId &&
    publicPage &&
    consent?.decision === "accepted" &&
    consent.expiresAt > Date.now();
  const session = useRef<ReturnType<typeof startMetrika> | null>(null);
  const consultationVisit = useRef<string | null>(null);
  const videoVisit = useRef<string | null>(null);
  const pageVisit = useRef<string | null>(null);

  function stop() {
    session.current?.dispose();
    session.current = null;
  }

  function choose(decision: Consent["decision"]) {
    if (decision === "rejected") stop();
    setConsent(saveAnalyticsConsent(decision));
    setOpen(false);
  }

  useEffect(() => {
    setConsent(loadAnalyticsConsent());
    setReady(true);
    function changed(event: StorageEvent) {
      if (event.key !== null && event.key !== ANALYTICS_CONSENT_KEY) return;
      const value = loadAnalyticsConsent();
      if (value?.decision !== "accepted") stop();
      setConsent(value);
    }
    window.addEventListener("storage", changed);
    return () => window.removeEventListener("storage", changed);
  }, []);

  useEffect(() => {
    if (!consent) return;
    let timer: number | undefined;
    function checkExpiry() {
      const remaining = consent!.expiresAt - Date.now();
      if (remaining <= 0) {
        stop();
        setConsent(null);
      } else
        timer = window.setTimeout(
          checkExpiry,
          Math.min(remaining, 2_147_483_647),
        );
    }
    checkExpiry();
    return () => window.clearTimeout(timer);
  }, [consent]);

  useEffect(() => {
    videoVisit.current = pageVisit.current = consultationVisit.current = null;
    setOpen(false);
  }, [location.key]);

  useEffect(() => {
    if (!allowed || !counterId) return;
    const analytics = startMetrika(counterId);
    session.current = analytics;
    return () => {
      analytics.dispose();
      session.current = null;
    };
  }, [counterId, allowed]);
  useEffect(() => {
    const analytics = session.current;
    if (!allowed || !analytics) return;
    analytics.page(
      location.pathname,
      location.search,
      pageVisit.current !== location.key,
    );
    pageVisit.current = location.key;
    if (
      location.pathname === "/contacts" &&
      consultationVisit.current !== location.key
    ) {
      analytics.goal("consultation_open", "/contacts");
      consultationVisit.current = location.key;
    }
  }, [
    allowed,
    counterId,
    location.pathname,
    location.search,
    location.hash,
    location.key,
  ]);
  return (
    <ConsentContext.Provider
      value={{
        available: ready && publicPage,
        prompt: !!counterId && consent === null,
        consent,
        open,
        setOpen,
        choose,
      }}
    >
      <AnalyticsContext.Provider
        value={(goal, path) => {
          if (
            !allowed ||
            !session.current ||
            !consent ||
            consent.expiresAt <= Date.now() ||
            path !== analyticsPath(location.pathname, location.search)
          )
            return;
          if (goal === "video_presentation_view") {
            if (videoVisit.current === location.key) return;
            videoVisit.current = location.key;
          }
          session.current.goal(goal, path);
        }}
      >
        {children}
      </AnalyticsContext.Provider>
    </ConsentContext.Provider>
  );
}

export function AnalyticsSettings() {
  const settings = useContext(ConsentContext);
  if (!settings?.available) return null;
  return (
    <Button variant="text" onClick={() => settings.setOpen(true)}>
      Настройки аналитики
    </Button>
  );
}

export function AnalyticsConsent() {
  const settings = useContext(ConsentContext);
  if (!settings?.available) return null;
  const content = (
    <>
      <p>
        Разрешить Яндекс Метрике учитывать просмотры публичных страниц и
        обращения за консультацией? Отказ не влияет на работу сайта.
      </p>
      <p className="muted">
        Выбор сохраняется в этом браузере на 180 дней. Его можно изменить в
        футере. Если браузер не позволяет сохранить выбор, при следующем
        посещении потребуется выбрать снова.
      </p>
      {settings.consent && (
        <p>
          Ваш выбор:{" "}
          {settings.consent.decision === "accepted"
            ? "аналитика разрешена"
            : "аналитика отклонена"}
          .
        </p>
      )}
      <div className="actions">
        <Button onClick={() => settings.choose("rejected")}>Отклонить</Button>
        <Button onClick={() => settings.choose("accepted")}>Разрешить</Button>
      </div>
    </>
  );
  return (
    <>
      {settings.prompt && !settings.open && (
        <section
          className="card analytics-consent"
          aria-labelledby="analytics-consent-title"
        >
          <h2 id="analytics-consent-title">Настройки аналитики</h2>
          {content}
        </section>
      )}
      <Modal
        open={settings.open}
        title="Настройки аналитики"
        onClose={() => settings.setOpen(false)}
      >
        {content}
      </Modal>
    </>
  );
}
