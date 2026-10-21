import { describe, expect, it, vi } from "vitest";
import { ApiError, createApiClient } from "../app/lib/api/client";
import { takeMagicToken } from "../app/lib/api/magic-link";

describe("API security", () => {
  it("gets fresh CSRF before every mutation and sends cookies", async () => {
    const calls: Request[] = [];
    const fetcher = vi.fn(async (input: RequestInfo | URL) => {
      const request = input as Request;
      calls.push(request);
      return request.url.endsWith("/csrf")
        ? Response.json({ csrf_token: `csrf-${calls.length}` })
        : new Response(null, { status: 204 });
    });
    const client = createApiClient("https://sinegor.test", fetcher);
    await client.POST("/api/auth/logout");
    await client.POST("/api/auth/logout");
    expect(calls).toHaveLength(4);
    expect(calls[1].headers.get("X-CSRF-Token")).toBe("csrf-1");
    expect(calls[3].headers.get("X-CSRF-Token")).toBe("csrf-3");
    expect(
      calls.every(
        (request) =>
          request.credentials === "same-origin" && request.cache === "no-store",
      ),
    ).toBe(true);
  });
  it("does not perform a mutation if CSRF is unavailable", async () => {
    const fetcher = vi.fn(async () => new Response(null, { status: 503 }));
    await expect(
      createApiClient("https://sinegor.test", fetcher).POST("/api/auth/logout"),
    ).rejects.toBeInstanceOf(ApiError);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("preserves the saved customer ID when invitation delivery fails", async () => {
    const customerId = "00000000-0000-0000-0000-000000000001";
    const client = createApiClient("https://sinegor.test", async (input) =>
      (input as Request).url.endsWith("/csrf")
        ? Response.json({ csrf_token: "csrf-token" })
        : Response.json(
            {
              error: {
                code: "http_503",
                message: "Customer saved; invitation failed. Retry invitation",
              },
              request_id: "request-1",
            },
            {
              status: 503,
              headers: {
                "X-Customer-ID": customerId,
                "X-Request-ID": "request-1",
              },
            },
          ),
    );
    await expect(
      client.POST("/api/admin/customers", {
        body: { email: "customer@example.test" },
      }),
    ).rejects.toMatchObject({
      status: 503,
      requestId: "request-1",
      customerId,
    });
  });
  it("uses null when an API error has no saved customer ID", async () => {
    const client = createApiClient(
      "https://sinegor.test",
      async () => new Response(null, { status: 401 }),
    );
    await expect(client.GET("/api/auth/session")).rejects.toMatchObject({
      status: 401,
      requestId: null,
      customerId: null,
    });
  });
  it("does not expose response bodies in errors", async () => {
    const client = createApiClient(
      "https://sinegor.test",
      async () => new Response("private-data", { status: 500 }),
    );
    await expect(client.GET("/api/auth/session")).rejects.toThrow(
      "Не удалось выполнить запрос",
    );
  });
  it("removes token from history without submitting it", () => {
    const replaceState = vi.fn();
    const token = "a".repeat(43);
    expect(
      takeMagicToken(
        { hash: `#token=${token}`, pathname: "/auth/magic-link", search: "" },
        { state: null, replaceState },
      ),
    ).toBe(token);
    expect(replaceState).toHaveBeenCalledWith(null, "", "/auth/magic-link");
  });
  it("rejects malformed token and clears the fragment", () => {
    const replaceState = vi.fn();
    expect(
      takeMagicToken(
        { hash: "#token=invalid", pathname: "/auth/magic-link", search: "" },
        { state: null, replaceState },
      ),
    ).toBeNull();
    expect(replaceState).toHaveBeenCalledOnce();
  });
});
