import { afterEach, describe, expect, it, vi } from "vitest";
import {
  canonicalUrl,
  normalizePublicPath,
  publicationOffset,
} from "../app/lib/public-url";
import { publicOrigin, publicRedirect } from "../app/lib/public-url.server";

afterEach(() => vi.unstubAllEnvs());

describe("public document addresses", () => {
  it.each([
    ["/ABOUT/", "/about"],
    ["/pages/about", "/about"],
    ["/PAGES/home/", "/"],
    ["/pages/contacts", "/contacts"],
    ["/pages/publications", "/publications"],
    ["/CONTACTS/", "/contacts"],
    ["/PUBLICATIONS/", "/publications"],
    ["/Services/ai-analysis/", "/services/ai-analysis"],
    ["/SERVICES/technical/", "/services/technical"],
    ["/%61bout", "/about"],
    ["/pages/%41bout/", "/pages/About"],
    ["/Publications/Case-Sensitive/", "/publications/Case-Sensitive"],
    ["/services/TECHNICAL", "/services/TECHNICAL"],
    ["/pages/ABOUT", "/pages/ABOUT"],
    ["/pages/_", "/pages/%5F"],
    ["/pages/%5f", "/pages/%5F"],
    ["/services/_", "/services/%5F"],
    ["/publications/_", "/publications/%5F"],
  ])("normalizes %s to %s without folding CMS slug case", (path, expected) => {
    expect(normalizePublicPath(path)).toBe(expected);
  });

  it.each([
    "/auth/login/",
    "/customer/orders",
    "/admin",
    "/unknown",
    "/api/orders",
  ])("leaves private, API and unknown paths alone: %s", (path) =>
    expect(normalizePublicPath(path)).toBeNull(),
  );

  it("keeps meaningful pagination and omits tracking, zero offsets and fragments", () => {
    expect(
      canonicalUrl("https://sinegor.example", "/about", "?utm_source=test"),
    ).toBe("https://sinegor.example/about");
    expect(
      canonicalUrl(
        "https://sinegor.example",
        "/publications",
        "?offset=25&utm_source=test",
      ),
    ).toBe("https://sinegor.example/publications?offset=25");
    expect(
      canonicalUrl("https://sinegor.example", "/publications", "?offset=0"),
    ).toBe("https://sinegor.example/publications");
  });

  it.each(["-1", "1.2", "NaN", "Infinity", "9007199254740992"])(
    "uses the first publication page for invalid offset %s",
    (offset) => expect(publicationOffset(`?offset=${offset}`)).toBe(0),
  );

  it("uses the configured public origin instead of internal or forwarded hosts", () => {
    vi.stubEnv("PUBLIC_ORIGIN", "https://sinegor.example/");
    const request = new Request("http://ssr.internal:3000/about/", {
      headers: { "X-Forwarded-Host": "untrusted.example" },
    });
    expect(publicOrigin(request)).toBe("https://sinegor.example");
    expect(publicRedirect(request)?.headers.get("Location")).toBe(
      "https://sinegor.example/about",
    );
  });

  it.each([
    "ftp://example.com",
    "https://user:pass@example.com",
    "https://example.com/subpath",
    "https://example.com?query=1",
    "https://example.com/#fragment",
  ])("rejects invalid public origin %s", (origin) => {
    vi.stubEnv("PUBLIC_ORIGIN", origin);
    expect(() => publicOrigin(new Request("http://localhost/about"))).toThrow();
  });

  it("redirects once, normalizes catalogue parameters and preserves tracking elsewhere", () => {
    vi.stubEnv("PUBLIC_ORIGIN", "https://sinegor.example");
    const response = publicRedirect(
      new Request(
        "http://localhost/PAGES/publications/?offset=025&utm_source=test",
      ),
    );
    expect(response?.status).toBe(308);
    expect(response?.headers.get("Location")).toBe(
      "https://sinegor.example/publications?offset=25",
    );
    expect(
      publicRedirect(
        new Request("http://localhost/publications?offset=25&utm_source=test"),
      )?.headers.get("Location"),
    ).toBe("https://sinegor.example/publications?offset=25");
    expect(
      publicRedirect(new Request("http://localhost/about?utm_source=test")),
    ).toBeNull();
    expect(
      publicRedirect(new Request("http://localhost/ABOUT", { method: "POST" })),
    ).toBeNull();
  });

  it.each([
    ["/ABOUT.data", "/about"],
    ["/about/_.data", "/about"],
    ["/PAGES/about.data", "/about"],
    [
      "/pages/about.data?_routes=routes%2Fpublic%2Fpage&utm_source=test",
      "/about?utm_source=test",
    ],
    [
      "/publications.data?offset=0&_routes=routes%2Fpublic%2Fpublications",
      "/publications",
    ],
  ])(
    "redirects framework data request %s to document address %s",
    (path, target) => {
      vi.stubEnv("PUBLIC_ORIGIN", "https://sinegor.example");
      const response = publicRedirect(new Request(`http://localhost${path}`));
      expect(response?.status).toBe(308);
      expect(response?.headers.get("Location")).toBe(
        `https://sinegor.example${target}`,
      );
    },
  );

  it("does not redirect an already canonical framework data request", () => {
    expect(publicRedirect(new Request("http://localhost/_.data"))).toBeNull();
    expect(
      publicRedirect(new Request("http://localhost/about.data")),
    ).toBeNull();
    expect(
      publicRedirect(
        new Request(
          "http://localhost/publications.data?offset=25&_routes=routes%2Fpublic%2Fpublications",
        ),
      ),
    ).toBeNull();
  });
});
