import { tr } from "@/i18n";
import { config } from "@/lib/config";
import { ApiError } from "./errors";

type Method = "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
type Query = Record<string, string | number | boolean | Array<string | number> | null | undefined>;

export interface RequestOptions {
  query?: Query;
  body?: unknown;
  signal?: AbortSignal;
  timeoutMs?: number;
}

export function buildUrl(path: string, query?: Query, base = config.apiBaseUrl): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value === undefined || value === null) continue;
    for (const item of Array.isArray(value) ? value : [value]) params.append(key, String(item));
  }
  const qs = params.toString();
  return `${base}${path}${qs ? `?${qs}` : ""}`;
}

/**
 * Minimal typed fetch wrapper.
 * - Same-origin cookie session (`credentials: "include"`); no tokens in JS.
 * - Every non-2xx response becomes an `ApiError` built from RFC 9457 problem details.
 * - Requests time out, and abort cleanly when React Query cancels them.
 * - Never cached: the backend sends `Cache-Control: no-store` and the service worker
 *   is configured NetworkOnly for `/api`.
 */
export async function request<T>(method: Method, path: string, options: RequestOptions = {}): Promise<T> {
  if (config.demoMode) throw new ApiError({ title: tr("copy.this_presentation_uses_synthetic_demo_data_cb96de0"), status: 403, code: "demo_sandbox", detail: tr("copy.live_api_access_is_disabled_in_demo_mode_58dc8ba") });
  const timeout = AbortSignal.timeout(options.timeoutMs ?? config.requestTimeoutMs);
  const signal = options.signal ? AbortSignal.any([options.signal, timeout]) : timeout;
  const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;

  let response: Response;
  try {
    response = await fetch(buildUrl(path, options.query), {
      method,
      signal,
      credentials: "include",
      cache: "no-store",
      headers: {
        Accept: "application/json, application/problem+json",
        ...(options.body !== undefined && !isFormData ? { "Content-Type": "application/json" } : {}),
      },
      body:
        options.body === undefined
          ? undefined
          : isFormData
            ? (options.body as FormData)
            : JSON.stringify(options.body),
    });
  } catch (error) {
    if (options.signal?.aborted) throw error; // caller cancelled: let React Query handle it
    if (timeout.aborted) throw ApiError.network(tr("copy.the_request_took_too_long_9dff5e6"), "timeout");
    throw ApiError.network(tr("copy.network_request_failed_6219c84"));
  }

  if (response.status === 204) return undefined as T;
  const text = await response.text();
  let body: unknown = undefined;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }
  if (!response.ok) {
    throw ApiError.fromResponse(response.status, body, response.headers.get("x-request-id"));
  }
  return body as T;
}

export const api = {
  get: <T>(path: string, options?: Omit<RequestOptions, "body">) => request<T>("GET", path, options),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>("POST", path, { ...options, body }),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>("PATCH", path, { ...options, body }),
  delete: <T>(path: string, options?: RequestOptions) => request<T>("DELETE", path, options),
};
