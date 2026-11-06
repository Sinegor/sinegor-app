export const ANALYTICS_CONSENT_KEY = "sinegor.analytics-consent.v1";
export const ANALYTICS_TEXT_VERSION = "1";
const lifetimeDays = 180;
const uuid =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const withdrawalKey = `${ANALYTICS_CONSENT_KEY}.withdrawal`;
const withdrawalAckKey = `${withdrawalKey}.ack`;
const withdrawalCookie = "sinegor_analytics_withdrawal";

export type ConsentEvent = {
  event_id: string;
  browser_id: string;
  event_type: "grant" | "withdraw";
  text_version: string;
};
export type AnalyticsConsent = {
  decision: "accepted" | "rejected";
  savedAt: number;
  expiresAt: number;
  textVersion: string;
  browserId?: string;
  barrier?: string;
  barrierRevision?: number;
  pending?: ConsentEvent;
};
function expiry(savedAt: number) {
  const date = new Date(savedAt);
  date.setUTCDate(date.getUTCDate() + lifetimeDays);
  return date.getTime();
}
function object(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}
function isEvent(value: unknown): value is ConsentEvent {
  return (
    object(value) &&
    typeof value.event_id === "string" &&
    uuid.test(value.event_id) &&
    typeof value.browser_id === "string" &&
    uuid.test(value.browser_id) &&
    ["grant", "withdraw"].includes(String(value.event_type)) &&
    typeof value.text_version === "string" &&
    /^[A-Za-z0-9._-]{1,32}$/.test(value.text_version)
  );
}
function parse(serialized: string | null): AnalyticsConsent | null {
  try {
    const value: unknown = JSON.parse(serialized || "null");
    if (
      !object(value) ||
      !["accepted", "rejected"].includes(String(value.decision)) ||
      !Number.isSafeInteger(value.savedAt) ||
      !Number.isSafeInteger(value.expiresAt) ||
      typeof value.textVersion !== "string" ||
      !/^[A-Za-z0-9._-]{1,32}$/.test(value.textVersion) ||
      (value.barrierRevision !== undefined &&
        (!Number.isSafeInteger(value.barrierRevision) ||
          Number(value.barrierRevision) < 0)) ||
      (value.barrier !== undefined &&
        (typeof value.barrier !== "string" || !uuid.test(value.barrier))) ||
      (value.browserId !== undefined &&
        (typeof value.browserId !== "string" || !uuid.test(value.browserId))) ||
      (value.pending !== undefined &&
        (!isEvent(value.pending) ||
          value.pending.browser_id !== value.browserId)) ||
      (value.decision === "accepted" && (!value.browserId || value.pending))
    )
      return null;
    return value as AnalyticsConsent;
  } catch {
    return null;
  }
}
function get(key: string) {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}
function cookieBarrier() {
  try {
    const prefix = `${withdrawalCookie}=`;
    const value = document.cookie
      .split("; ")
      .find((item) => item.startsWith(prefix));
    return parse(value ? decodeURIComponent(value.slice(prefix.length)) : null);
  } catch {
    return null;
  }
}
function barrier() {
  // Either durable store can refuse a write while retaining an older value.
  // A per-browser revision orders withdrawals even within the same millisecond.
  const candidates = [cookieBarrier(), parse(get(withdrawalKey))].filter(
    (value): value is AnalyticsConsent => value !== null,
  );
  candidates.sort(
    (left, right) =>
      (right.barrierRevision ?? 0) - (left.barrierRevision ?? 0) ||
      right.savedAt - left.savedAt ||
      (right.barrier ?? "").localeCompare(left.barrier ?? ""),
  );
  const value = candidates[0];
  if (value?.pending && get(withdrawalAckKey) === value.pending.event_id) {
    const saved = { ...value };
    delete saved.pending;
    return saved;
  }
  return value;
}
function read(): AnalyticsConsent | null {
  const value = parse(get(ANALYTICS_CONSENT_KEY));
  const revoked = barrier();
  // A separate barrier cannot be overwritten by a late grant's read/write race.
  if (
    revoked &&
    ((revoked.barrierRevision ?? 0) !== (value?.barrierRevision ?? 0) ||
      revoked.barrier !== value?.barrier ||
      value?.pending?.event_type === "withdraw" ||
      !value)
  )
    return revoked;
  return value;
}
function saveBarrier(value: AnalyticsConsent) {
  const serialized = JSON.stringify(value);
  let cookieSaved = false;
  try {
    document.cookie = `${withdrawalCookie}=${encodeURIComponent(serialized)}; Path=/; SameSite=Lax; Max-Age=${lifetimeDays * 86400}`;
    cookieSaved =
      cookieBarrier()?.barrier === value.barrier &&
      cookieBarrier()?.pending?.event_id === value.pending?.event_id;
  } catch {
    /* localStorage remains the primary durable store. */
  }
  let storageSaved = false;
  try {
    window.localStorage.setItem(withdrawalKey, serialized);
    storageSaved = get(withdrawalKey) === serialized;
  } catch {
    /* A small first-party cookie preserves withdrawal when quota is exhausted. */
  }
  if (!storageSaved && !cookieSaved)
    throw new Error("Cannot persist withdrawal");
}
export function loadAnalyticsConsent(): AnalyticsConsent | null {
  const value = read();
  if (
    !value ||
    value.savedAt > Date.now() ||
    value.expiresAt !== expiry(value.savedAt) ||
    value.expiresAt <= Date.now() ||
    value.textVersion !== ANALYTICS_TEXT_VERSION
  )
    return null;
  return value;
}
function write(value: AnalyticsConsent) {
  const serialized = JSON.stringify(value);
  window.localStorage.setItem(ANALYTICS_CONSENT_KEY, serialized);
  if (window.localStorage.getItem(ANALYTICS_CONSENT_KEY) !== serialized)
    throw new Error("Storage unavailable");
}
function decision(
  value: AnalyticsConsent["decision"],
  browserId?: string,
): AnalyticsConsent {
  const savedAt = Date.now();
  return {
    decision: value,
    savedAt,
    expiresAt: expiry(savedAt),
    textVersion: ANALYTICS_TEXT_VERSION,
    ...(browserId ? { browserId } : {}),
  };
}

// A pending grant is a local prohibition until the matching committed receipt arrives.
// Retry its UUID after a lost response; replacing the pending event invalidates late receipts.
export class AnalyticsConsentJournal {
  consent: AnalyticsConsent | null = loadAnalyticsConsent();
  busy = false;
  error: string | null = null;
  private revision = 0;
  private sendingWithdrawal = false;
  private pendingMemory: AnalyticsConsent | null = null;
  constructor(
    private send: (event: ConsentEvent) => Promise<unknown>,
    private changed: () => void,
  ) {}
  sync() {
    this.revision++;
    this.consent = loadAnalyticsConsent();
    this.busy = false;
    this.error = null;
    this.changed();
  }
  async choose(choice: AnalyticsConsent["decision"]) {
    if (choice === "accepted" && this.busy) return;
    const revision = ++this.revision;
    this.error = null;
    const previous = this.pendingMemory || read();
    if (choice === "rejected") {
      const value = decision("rejected", previous?.browserId);
      if (value.browserId)
        value.pending =
          previous?.pending?.event_type === "withdraw"
            ? previous.pending
            : {
                event_id: crypto.randomUUID(),
                browser_id: value.browserId,
                event_type: "withdraw",
                text_version: previous?.textVersion || ANALYTICS_TEXT_VERSION,
              };
      this.consent = value;
      this.busy = false;
      value.barrierRevision =
        (previous?.barrierRevision ?? 0) +
        (previous?.pending?.event_type === "withdraw" ? 0 : 1);
      value.barrier =
        previous?.pending?.event_type === "withdraw"
          ? previous.barrier
          : value.pending?.event_id;
      try {
        saveBarrier(value);
        this.pendingMemory = null;
        try {
          write(value);
        } catch {
          /* The independent withdrawal barrier is durable. */
        }
      } catch {
        this.pendingMemory = value;
        try {
          window.localStorage.removeItem(ANALYTICS_CONSENT_KEY);
        } catch {
          /* Both browser persistence mechanisms are unavailable. */
        }
        this.error =
          "Аналитика отключена. Не удалось сохранить выбор в браузере; проверьте его настройки.";
      }
      this.changed();
      await this.retryWithdrawal();
      return;
    }
    if (previous?.pending?.event_type === "withdraw") {
      this.error =
        "Аналитика отключена. Дождитесь сохранения отзыва и повторите разрешение.";
      this.changed();
      await this.retryWithdrawal();
      return;
    }
    const value = decision(
      "rejected",
      previous?.browserId || crypto.randomUUID(),
    );
    value.barrier = previous?.barrier;
    value.barrierRevision = previous?.barrierRevision;
    value.pending =
      previous?.pending?.event_type === "grant" &&
      previous.pending.text_version === ANALYTICS_TEXT_VERSION
        ? previous.pending
        : {
            event_id: crypto.randomUUID(),
            browser_id: value.browserId!,
            event_type: "grant",
            text_version: ANALYTICS_TEXT_VERSION,
          };
    try {
      write(value);
    } catch {
      this.error =
        "Не удалось сохранить выбор в браузере. Аналитика отключена; проверьте настройки браузера и повторите.";
      this.changed();
      return;
    }
    this.consent = value;
    this.busy = true;
    this.changed();
    try {
      const receipt = await this.send(value.pending);
      if (!this.matches(receipt, value.pending))
        throw new Error("Invalid receipt");
      if (
        revision !== this.revision ||
        read()?.pending?.event_id !== value.pending.event_id
      )
        return;
      const accepted = decision("accepted", value.browserId);
      accepted.barrier = value.barrier;
      accepted.barrierRevision = value.barrierRevision;
      write(accepted);
      this.consent = loadAnalyticsConsent();
      if (this.consent?.decision !== "accepted")
        throw new Error("Permission superseded");
    } catch {
      if (revision === this.revision)
        this.error =
          "Не удалось сохранить разрешение на сервере. Аналитика отключена. Повторите попытку.";
    } finally {
      if (revision === this.revision) {
        this.busy = false;
        this.changed();
      }
    }
  }
  async retryWithdrawal() {
    const value = this.pendingMemory || read();
    const event = value?.pending;
    if (!value || event?.event_type !== "withdraw" || this.sendingWithdrawal)
      return;
    this.sendingWithdrawal = true;
    try {
      const receipt = await this.send(event);
      if (!this.matches(receipt, event)) throw new Error("Invalid receipt");
      const current = this.pendingMemory || read();
      if (current?.pending?.event_id !== event.event_id) return;
      const saved = { ...current };
      delete saved.pending;
      // Never rewrite the barrier: a concurrent withdrawal must survive this receipt.
      window.localStorage.setItem(withdrawalAckKey, event.event_id);
      if (get(withdrawalAckKey) !== event.event_id)
        throw new Error("Cannot persist receipt");
      try {
        write(saved);
      } catch {
        /* Barrier + receipt already preserve the prohibition. */
      }
      this.pendingMemory = null;
      this.consent = loadAnalyticsConsent();
      this.error = null;
    } catch {
      this.error =
        "Аналитика отключена. Отзыв будет отправлен автоматически после восстановления связи.";
    } finally {
      this.sendingWithdrawal = false;
      this.changed();
    }
  }
  private matches(receipt: unknown, event: ConsentEvent) {
    return (
      object(receipt) &&
      receipt.event_id === event.event_id &&
      receipt.event_type === event.event_type &&
      receipt.text_version === event.text_version &&
      typeof receipt.recorded_at === "string" &&
      /^\d{4}-\d\d-\d\dT.*(?:Z|\+00:00)$/.test(receipt.recorded_at) &&
      Number.isFinite(Date.parse(receipt.recorded_at))
    );
  }
}
