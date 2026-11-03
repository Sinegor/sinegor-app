import { afterEach, expect, it, vi } from "vitest";
import {
  loadAnalyticsConsent,
  saveAnalyticsConsent,
} from "../app/lib/analytics-consent";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function storage(initial: string | null = null) {
  let value = initial;
  const localStorage = {
    getItem: () => value,
    setItem: (_key: string, next: string) => {
      value = next;
    },
  };
  vi.stubGlobal("window", { localStorage });
  return localStorage;
}

it("keeps either explicit choice across visits and requires a new choice after expiry", () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-11-02T12:00:00Z"));
  storage();
  expect(loadAnalyticsConsent()).toBeNull();
  for (const decision of ["accepted", "rejected"] as const) {
    saveAnalyticsConsent(decision);
    expect(loadAnalyticsConsent()?.decision).toBe(decision);
  }
  vi.setSystemTime(new Date("2027-06-01T12:00:00Z"));
  expect(loadAnalyticsConsent()).toBeNull();
});

it.each([
  "invalid-json",
  "null",
  "true",
  "[]",
  '{"decision":"accepted"}',
  '{"decision":"accepted","expiresAt":"never"}',
  '{"decision":"unknown","expiresAt":9999999999999}',
  '{"decision":"accepted","expiresAt":1}',
])(
  "does not authorize tracking with malformed or expired storage: %s",
  (value) => {
    storage(value);
    expect(loadAnalyticsConsent()).toBeNull();
  },
);

it("does not authorize tracking without browser storage and keeps an explicit choice in memory", () => {
  vi.stubGlobal("window", {
    get localStorage() {
      throw new Error("Storage unavailable");
    },
  });
  expect(loadAnalyticsConsent()).toBeNull();
  expect(saveAnalyticsConsent("rejected").decision).toBe("rejected");
  expect(saveAnalyticsConsent("accepted").decision).toBe("accepted");
});
