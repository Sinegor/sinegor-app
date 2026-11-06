import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Link, useLocation, useMatches } from "react-router";
import { analyticsPath, type AnalyticsGoal } from "../lib/analytics";
import { startMetrika } from "../lib/metrika.client";
import {
  ANALYTICS_CONSENT_KEY,
  AnalyticsConsentJournal,
  type AnalyticsConsent as Consent,
} from "../lib/analytics-consent";
import { Button, Modal } from "./ui";
import { browserApi } from "../lib/api/client";

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
  close: () => void;
  busy: boolean;
  error: string | null;
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
  const [dismissed, setDismissed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const journal = useRef<AnalyticsConsentJournal | null>(null);
  const channel = useRef<BroadcastChannel | null>(null);
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

  async function choose(decision: Consent["decision"]) {
    if (!journal.current) return;
    if (decision === "rejected") {
      stop();
      setOpen(false);
    }
    setDismissed(false);
    const operation = journal.current.choose(decision);
    channel.current?.postMessage("changed");
    await operation;
    channel.current?.postMessage("changed");
    if (journal.current.error) {
      if (decision === "rejected") setOpen(true);
    } else setOpen(false);
  }

  function close() {
    setOpen(false);
    setDismissed(true);
  }

  useEffect(() => {
    const state = new AnalyticsConsentJournal(
      async (event) => {
        const { data } = await browserApi().POST("/api/analytics/consent", {
          body: event,
        });
        return data;
      },
      () => {
        if (state.consent?.decision !== "accepted") stop();
        setConsent(state.consent);
        setBusy(state.busy);
        setError(state.error);
      },
    );
    journal.current = state;
    setConsent(state.consent);
    setReady(true);
    function changed(event?: StorageEvent) {
      if (
        event &&
        event.key !== null &&
        !event.key.startsWith(ANALYTICS_CONSENT_KEY)
      )
        return;
      state.sync();
      setOpen(false);
      setDismissed(false);
      void state.retryWithdrawal();
    }
    function retry() {
      void state.retryWithdrawal();
    }
    try {
      channel.current = new BroadcastChannel(ANALYTICS_CONSENT_KEY);
      channel.current.onmessage = () => changed();
    } catch {
      /* Storage events still synchronize ordinary browser tabs. */
    }
    window.addEventListener("storage", changed);
    window.addEventListener("online", retry);
    const timer = window.setInterval(retry, 60_000);
    retry();
    return () => {
      state.sync();
      journal.current = null;
      window.removeEventListener("storage", changed);
      window.removeEventListener("online", retry);
      window.clearInterval(timer);
      channel.current?.close();
      channel.current = null;
    };
  }, []);

  useEffect(() => {
    if (!consent) return;
    let timer: number | undefined;
    function checkExpiry() {
      const remaining = consent!.expiresAt - Date.now();
      if (remaining <= 0) {
        stop();
        journal.current?.sync();
        setDismissed(false);
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
        prompt:
          !!counterId &&
          (consent === null || consent.pending?.event_type === "grant") &&
          !dismissed,
        consent,
        open,
        setOpen,
        choose,
        close,
        busy,
        error,
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
        Мы используем Яндекс Метрику, чтобы понимать, как посетители пользуются
        сайтом, и улучшать его работу.
      </p>
      <p>Сервис собирает технические данные и сведения о действиях на сайте.</p>
      <p>
        Подробнее —{" "}
        <Link to="/documents/privacy-policy" onClick={settings.close}>
          Политика обработки персональных данных
        </Link>
        .
      </p>
      {settings.consent && !settings.consent.pending && (
        <p>
          Ваш выбор:{" "}
          {settings.consent.decision === "accepted"
            ? "аналитика разрешена"
            : "аналитика отклонена"}
          .
        </p>
      )}
      {settings.busy && (
        <p role="status">Сохраняем разрешение… Аналитика пока отключена.</p>
      )}
      {settings.error && <p role="alert">{settings.error}</p>}
      <div className="actions">
        <Button onClick={() => settings.choose("rejected")}>Отклонить</Button>
        <Button
          disabled={settings.busy}
          onClick={() => settings.choose("accepted")}
        >
          Разрешить
        </Button>
      </div>
    </>
  );
  const showing = settings.open || settings.prompt;
  return (
    <Modal
      open={showing}
      title={settings.open ? "Настройки аналитики" : "Статистика посещений"}
      onClose={() => {
        // A prop-driven close after a decision must not suppress a future prompt.
        if (showing) settings.close();
      }}
    >
      {content}
    </Modal>
  );
}
