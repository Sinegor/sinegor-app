import { afterEach, expect, it, vi } from "vitest";
import { analyticsConfig } from "../app/lib/analytics.server";
import { analyticsPath, createAnalytics } from "../app/lib/analytics";

afterEach(() => vi.unstubAllEnvs());
it("requires an explicit production opt-in and a valid counter ID", () => {
  vi.stubEnv("NODE_ENV", "production");
  vi.stubEnv("YANDEX_METRIKA_ENABLED", "true");
  vi.stubEnv("YANDEX_METRIKA_ID", "12345678");
  expect(analyticsConfig()).toEqual({ counterId: 12345678 });
  for (const mode of ["development", "test"]) {
    vi.stubEnv("NODE_ENV", mode);
    expect(analyticsConfig()).toBeNull();
  }
  vi.stubEnv("NODE_ENV", "production");
  vi.stubEnv("YANDEX_METRIKA_ID", "invalid");
  expect(analyticsConfig()).toBeNull();
  vi.stubEnv("YANDEX_METRIKA_ID", "12345678");
  vi.stubEnv("YANDEX_METRIKA_ENABLED", "false");
  expect(analyticsConfig()).toBeNull();
});

it("never treats private or unknown paths as analytics pages and strips arbitrary URL data", () => {
  for (const path of [
    "/auth/magic-link",
    "/auth/login",
    "/admin",
    "/admin/orders/secret",
    "/customer/orders/secret",
    "/unknown",
  ])
    expect(analyticsPath(path, "?token=secret#secret")).toBeNull();
  expect(analyticsPath("/about", "?email=secret@example.test#token")).toBe(
    "/about",
  );
  expect(analyticsPath("/publications", "?offset=25&token=secret")).toBe(
    "/publications?offset=25",
  );
});

it("initializes manual tracking, deduplicates page views and records service goals", () => {
  const send = vi.fn();
  const analytics = createAnalytics(
    send,
    "https://sinegor.example",
    "https://search.example/?email=secret",
  );
  analytics.page("/", "?token=secret");
  analytics.page("/", "?email=secret");
  analytics.page("/services/ai-analysis");
  expect(send.mock.calls.filter(([method]) => method === "hit")).toHaveLength(
    2,
  );
  expect(
    send.mock.calls.filter(
      ([method, goal]) => method === "reachGoal" && goal === "service_view",
    ),
  ).toHaveLength(1);
  expect(send.mock.calls[0]).toMatchObject([
    "init",
    {
      defer: true,
      webvisor: false,
      clickmap: false,
      trackLinks: false,
      accurateTrackBounce: false,
      trackHash: false,
      sendTitle: false,
      disableYtm: true,
    },
  ]);
  expect(JSON.stringify(send.mock.calls)).not.toMatch(/secret|email=|token=/);
  expect(
    send.mock.calls.find(([method]) => method === "hit")?.[2],
  ).toMatchObject({
    referer: "https://search.example/",
    title: "SINEGOR LAB",
    params: { event: "page_view" },
  });
});

it("does not send goals on private routes, after disposal or for a previous page", () => {
  const send = vi.fn();
  const analytics = createAnalytics(
    send,
    "https://sinegor.example",
    "https://sinegor.example/auth/magic-link?token=secret",
  );
  analytics.page("/contacts");
  analytics.page("/documents");
  analytics.goal("consultation_submit", "/contacts");
  analytics.page("/admin/orders/217");
  analytics.goal("consultation_submit", "/admin/orders/217");
  expect(
    send.mock.calls.filter(([method]) => method === "reachGoal"),
  ).toHaveLength(0);
  analytics.dispose();
  const count = send.mock.calls.length;
  analytics.page("/contacts");
  analytics.goal("consultation_submit", "/contacts");
  expect(send).toHaveBeenCalledTimes(count);
  expect(JSON.stringify(send.mock.calls)).not.toMatch(/secret|217|magic-link/);
});

it("cannot break the site when the analytics API throws or rejects", async () => {
  const analytics = createAnalytics(
    () => {
      throw new Error("blocked");
    },
    "https://sinegor.example",
    "",
  );
  expect(() => {
    analytics.page("/contacts");
    analytics.goal("consultation_submit", "/contacts");
    analytics.dispose();
  }).not.toThrow();
  const rejected = createAnalytics(
    () => Promise.reject(new Error("blocked")),
    "https://sinegor.example",
    "",
  );
  rejected.page("/");
  await Promise.resolve();
});

it("restores a counter without recounting an already tracked page visit", () => {
  const send = vi.fn();
  const analytics = createAnalytics(send, "https://sinegor.example", "");
  analytics.page("/", "", false);
  expect(send.mock.calls.filter(([method]) => method === "init")).toHaveLength(
    1,
  );
  expect(send.mock.calls.filter(([method]) => method === "hit")).toHaveLength(
    0,
  );
  analytics.page("/services/ai-analysis");
  expect(send.mock.calls.filter(([method]) => method === "hit")).toHaveLength(
    1,
  );
});
