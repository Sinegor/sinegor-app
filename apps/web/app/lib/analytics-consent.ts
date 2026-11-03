export const ANALYTICS_CONSENT_KEY = "sinegor.analytics-consent.v1";
const consentLifetime = 180 * 24 * 60 * 60 * 1000;

export type AnalyticsConsent = {
  decision: "accepted" | "rejected";
  expiresAt: number;
};

export function loadAnalyticsConsent(): AnalyticsConsent | null {
  try {
    const value: unknown = JSON.parse(
      window.localStorage.getItem(ANALYTICS_CONSENT_KEY) || "null",
    );
    if (
      value &&
      typeof value === "object" &&
      "decision" in value &&
      (value.decision === "accepted" || value.decision === "rejected") &&
      "expiresAt" in value &&
      typeof value.expiresAt === "number" &&
      Number.isSafeInteger(value.expiresAt) &&
      value.expiresAt > Date.now() &&
      value.expiresAt <= Date.now() + consentLifetime
    )
      return { decision: value.decision, expiresAt: value.expiresAt };
  } catch {
    // Unavailable or invalid storage must never authorize tracking.
  }
  return null;
}

export function saveAnalyticsConsent(
  decision: AnalyticsConsent["decision"],
): AnalyticsConsent {
  const consent = { decision, expiresAt: Date.now() + consentLifetime };
  try {
    window.localStorage.setItem(ANALYTICS_CONSENT_KEY, JSON.stringify(consent));
  } catch {
    // An explicit choice still applies to this page when persistence is blocked.
  }
  return consent;
}
