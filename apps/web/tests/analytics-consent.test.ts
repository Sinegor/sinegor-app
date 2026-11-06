import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  ANALYTICS_CONSENT_KEY,
  AnalyticsConsentJournal,
  loadAnalyticsConsent,
  type ConsentEvent,
} from "../app/lib/analytics-consent";

const browserId = "2db9f30b-b3a6-4f46-9cb3-212ceea88e05";
let values: Map<string, string>;
function stored() {
  return JSON.parse(values.get(ANALYTICS_CONSENT_KEY) || "null");
}
function deferred() {
  let resolve!: (value: unknown) => void;
  const promise = new Promise<unknown>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
const ack = (event: ConsentEvent) => ({
  ...event,
  recorded_at: new Date().toISOString(),
});
beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-11-05T12:00:00Z"));
  values = new Map();
  vi.stubGlobal("window", {
    localStorage: {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
      removeItem: (key: string) => values.delete(key),
    },
  });
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it("does not trust legacy decisions without a reliable decision date and text version", () => {
  values.set(
    ANALYTICS_CONSENT_KEY,
    JSON.stringify({ decision: "accepted", expiresAt: Date.now() + 86400000 }),
  );
  expect(loadAnalyticsConsent()).toBeNull();
});
it("keeps initial rejection local without creating a browser identifier or an API event", async () => {
  const send = vi.fn();
  const journal = new AnalyticsConsentJournal(send, vi.fn());
  await journal.choose("rejected");
  expect(send).not.toHaveBeenCalled();
  expect(stored().browserId).toBeUndefined();
  expect(loadAnalyticsConsent()?.decision).toBe("rejected");
});
it("waits for a committed matching server acknowledgement before enabling analytics", async () => {
  const gate = deferred();
  const send = vi.fn((_event: ConsentEvent) => gate.promise);
  const journal = new AnalyticsConsentJournal(send, vi.fn());
  const choice = journal.choose("accepted");
  expect(loadAnalyticsConsent()?.decision).not.toBe("accepted");
  expect(send).toHaveBeenCalledTimes(1);
  const event = send.mock.calls[0][0];
  expect(event.event_type).toBe("grant");
  expect(event.text_version).toBe("1");
  expect(event.browser_id).toMatch(/^[0-9a-f-]{14}4[0-9a-f-]{21}$/i);
  gate.resolve(ack(event));
  await choice;
  expect(loadAnalyticsConsent()?.decision).toBe("accepted");
});
it("retries a grant with the same event identifier after an ambiguous failure", async () => {
  const send = vi.fn(async (event: ConsentEvent) => {
    if (send.mock.calls.length === 1) throw new Error("lost response");
    return ack(event);
  });
  const journal = new AnalyticsConsentJournal(send, vi.fn());
  await journal.choose("accepted");
  expect(loadAnalyticsConsent()?.decision).not.toBe("accepted");
  await journal.choose("accepted");
  expect(send.mock.calls[1][0]).toEqual(send.mock.calls[0][0]);
  expect(loadAnalyticsConsent()?.decision).toBe("accepted");
});
it("invalidates a late grant response when withdrawal happened meanwhile", async () => {
  const gate = deferred();
  const send = vi.fn((event: ConsentEvent) =>
    event.event_type === "grant" ? gate.promise : Promise.resolve(ack(event)),
  );
  const journal = new AnalyticsConsentJournal(send, vi.fn());
  const grant = journal.choose("accepted");
  const event = send.mock.calls[0][0];
  await journal.choose("rejected");
  gate.resolve(ack(event));
  await grant;
  expect(loadAnalyticsConsent()?.decision).toBe("rejected");
  expect(send.mock.calls.map((call) => call[0].event_type)).toEqual([
    "grant",
    "withdraw",
  ]);
});
it("retains a failed withdrawal through reload and retries the same event without enabling tracking", async () => {
  const send = vi.fn(async (event: ConsentEvent) => ack(event));
  const journal = new AnalyticsConsentJournal(send, vi.fn());
  await journal.choose("accepted");
  send.mockRejectedValueOnce(new Error("offline"));
  await journal.choose("rejected");
  const withdrawal = stored().pending;
  expect(withdrawal.event_type).toBe("withdraw");
  expect(loadAnalyticsConsent()?.decision).toBe("rejected");
  const reloaded = new AnalyticsConsentJournal(send, vi.fn());
  await reloaded.retryWithdrawal();
  expect(send.mock.calls.at(-1)?.[0]).toEqual(withdrawal);
  expect(stored().pending).toBeUndefined();
  expect(loadAnalyticsConsent()?.decision).toBe("rejected");
});
it("does not overwrite another tab's withdrawal with a late grant response", async () => {
  const gate = deferred();
  const first = new AnalyticsConsentJournal(() => gate.promise, vi.fn());
  const granting = first.choose("accepted");
  const event = stored().pending;
  const other = new AnalyticsConsentJournal(async (e) => ack(e), vi.fn());
  await other.choose("rejected");
  gate.resolve(ack(event));
  await granting;
  expect(loadAnalyticsConsent()?.decision).toBe("rejected");
});
it("fails closed if a new grant cannot be persisted", async () => {
  (window.localStorage.setItem as unknown) = () => {
    throw new Error("quota");
  };
  const send = vi.fn(async (event: ConsentEvent) => ack(event));
  const changed = vi.fn();
  const journal = new AnalyticsConsentJournal(send, changed);
  await journal.choose("accepted");
  expect(send).not.toHaveBeenCalled();
  expect(loadAnalyticsConsent()?.decision).not.toBe("accepted");
  expect(journal.error).toBeTruthy();
});
it("uses exactly 180 UTC calendar days and invalidates changed versions or fabricated expiry", async () => {
  const journal = new AnalyticsConsentJournal(
    async (event) => ack(event),
    vi.fn(),
  );
  await journal.choose("accepted");
  const value = stored();
  expect(new Date(value.expiresAt).toISOString()).toBe(
    "2027-05-04T12:00:00.000Z",
  );
  vi.setSystemTime(value.expiresAt - 1);
  expect(loadAnalyticsConsent()?.decision).toBe("accepted");
  vi.setSystemTime(value.expiresAt);
  expect(loadAnalyticsConsent()).toBeNull();
  vi.setSystemTime(new Date("2026-11-05T12:00:00Z"));
  for (const patch of [
    { textVersion: "old" },
    { expiresAt: value.expiresAt + 1 },
    { savedAt: Date.now() + 1 },
  ]) {
    values.set(
      ANALYTICS_CONSENT_KEY,
      JSON.stringify({ ...value, ...patch, browserId }),
    );
    expect(loadAnalyticsConsent()).toBeNull();
  }
});
it("a malformed or mismatched acknowledgement never grants analytics", async () => {
  const journal = new AnalyticsConsentJournal(
    async (event) => ({ ...ack(event), event_id: browserId }),
    vi.fn(),
  );
  await journal.choose("accepted");
  expect(loadAnalyticsConsent()?.decision).not.toBe("accepted");
  expect(journal.error).toBeTruthy();
});

it("cannot erase a withdrawal interleaved between a grant's storage read and write", async () => {
  const send = async (event: ConsentEvent) => ack(event);
  const first = new AnalyticsConsentJournal(send, vi.fn());
  const other = new AnalyticsConsentJournal(async () => {
    throw new Error("offline");
  }, vi.fn());
  const original = window.localStorage.setItem;
  let interleaved = false;
  window.localStorage.setItem = (key, serialized) => {
    if (
      !interleaved &&
      key === ANALYTICS_CONSENT_KEY &&
      JSON.parse(serialized).decision === "accepted"
    ) {
      interleaved = true;
      void other.choose("rejected");
    }
    original(key, serialized);
  };
  await first.choose("accepted");
  expect(loadAnalyticsConsent()?.decision).not.toBe("accepted");
  const retry = vi.fn(async (event: ConsentEvent) => ack(event));
  await new AnalyticsConsentJournal(retry, vi.fn()).retryWithdrawal();
  expect(retry.mock.calls[0][0].event_type).toBe("withdraw");
});

it("keeps withdrawal evidence in a durable cookie fallback when storage quota and network fail together", async () => {
  let cookie = "";
  vi.stubGlobal("document", {
    get cookie() {
      return cookie;
    },
    set cookie(value: string) {
      cookie = value.split(";")[0];
    },
  });
  const journal = new AnalyticsConsentJournal(
    async (event) => ack(event),
    vi.fn(),
  );
  await journal.choose("accepted");
  window.localStorage.setItem = () => {
    throw new Error("quota");
  };
  const offline = new AnalyticsConsentJournal(async () => {
    throw new Error("offline");
  }, vi.fn());
  await offline.choose("rejected");
  expect(loadAnalyticsConsent()?.decision).not.toBe("accepted");
  const send = vi.fn(async (event: ConsentEvent) => ack(event));
  await new AnalyticsConsentJournal(send, vi.fn()).retryWithdrawal();
  expect(send).toHaveBeenCalledTimes(1);
  expect(send.mock.calls[0][0].event_type).toBe("withdraw");
});

it("retries the newest durable withdrawal when an older cookie remains readable but cannot be updated", async () => {
  let cookie = "";
  let blockCookieWrites = false;
  vi.stubGlobal("document", {
    get cookie() {
      return cookie;
    },
    set cookie(value: string) {
      if (!blockCookieWrites) cookie = value.split(";")[0];
    },
  });
  const events: ConsentEvent[] = [];
  const send = async (event: ConsentEvent) => {
    events.push(event);
    return ack(event);
  };
  const journal = new AnalyticsConsentJournal(send, vi.fn());
  await journal.choose("accepted");
  await journal.choose("rejected");
  await journal.choose("accepted");
  blockCookieWrites = true;
  await journal.choose("rejected");
  // All choices happen at the same millisecond; timestamps cannot order the stores.
  expect(events.map((event) => event.event_type)).toEqual([
    "grant",
    "withdraw",
    "grant",
    "withdraw",
  ]);
  expect(loadAnalyticsConsent()?.decision).toBe("rejected");
  const reloaded = new AnalyticsConsentJournal(send, vi.fn());
  await reloaded.choose("accepted");
  expect(loadAnalyticsConsent()?.decision).toBe("accepted");
});
