import { afterEach, describe, expect, it, vi } from "vitest";
import { buildUrl, request } from "./client";
import { ApiError, describeError } from "./errors";

function respond(status: number, body: unknown, headers: Record<string, string> = {}) {
  return vi.fn().mockResolvedValue(
    new Response(body === undefined ? null : JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json", ...headers },
    }),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("buildUrl", () => {
  it("repeats array params and skips empty values", () => {
    expect(buildUrl("/governance/graph", { type: ["service", "authority"], q: undefined, x: null }, "/api/v1")).toBe(
      "/api/v1/governance/graph?type=service&type=authority",
    );
  });
});

describe("request", () => {
  it("returns parsed JSON and sends the session cookie", async () => {
    const fetchMock = respond(200, { status: "ok", version: "0.1.0" });
    vi.stubGlobal("fetch", fetchMock);
    await expect(request("GET", "/health")).resolves.toEqual({ status: "ok", version: "0.1.0" });
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(init.credentials).toBe("include");
    expect(init.cache).toBe("no-store");
  });

  it("turns problem details into ApiError", async () => {
    vi.stubGlobal(
      "fetch",
      respond(401, {
        type: "https://adapt.local/problems/session_missing",
        title: "Sign in to continue",
        status: 401,
        code: "session_missing",
        request_id: "abc123abc123",
      }),
    );
    const error = await request("GET", "/me").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe("session_missing");
    expect((error as ApiError).isUnauthorized).toBe(true);
  });

  it("maps non-problem failures to a generic error", async () => {
    vi.stubGlobal("fetch", respond(502, "Bad gateway", { "x-request-id": "req-1" }));
    const error = (await request("GET", "/health").catch((e: unknown) => e)) as ApiError;
    expect(error.code).toBe("http_502");
    expect(error.isRetryable).toBe(true);
  });

  it("reports network failures in the interface's voice", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const error = await request("GET", "/health").catch((e: unknown) => e);
    expect((error as ApiError).isNetwork).toBe(true);
    expect(describeError(error).title).toBe("Can't reach ADAPT");
  });

  it("serialises JSON bodies", async () => {
    const fetchMock = respond(200, {});
    vi.stubGlobal("fetch", fetchMock);
    await request("PATCH", "/me/preferences", { body: { faith_personalization: "declined" } });
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(init.body).toBe('{"faith_personalization":"declined"}');
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
  });
});
