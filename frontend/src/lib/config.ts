/**
 * Frontend runtime configuration, read once from Vite env (`VITE_*`, baked at build time).
 * Nothing secret ever lives here: the browser never holds API keys.
 */
function flag(value: string | undefined, fallback: boolean): boolean {
  if (value === undefined || value === "") return fallback;
  return ["1", "true", "yes", "on"].includes(value.toLowerCase());
}

/**
 * Where each capability's data comes from.
 *   live — only the real API. Capabilities whose endpoint hasn't shipped are gated off.
 *          Use this for real deployments.
 *   auto — the real API for every capability the backend reports as shipped
 *          (`/system/info → features`), typed in-memory mocks for the rest.
 *   mock — everything, including the session, from in-memory mocks. No backend needed.
 */
export type DataMode = "live" | "auto" | "mock";

function dataMode(value: string | undefined): DataMode {
  return value === "live" || value === "mock" ? value : "auto";
}

const demoMode = flag(import.meta.env.VITE_DEMO_MODE as string | undefined, false);

export const config = {
  /** Dedicated synthetic presentation sandbox. Never contacts the private/live API. */
  demoMode,
  /** Same-origin API prefix. The dev server and nginx both proxy it to the backend. */
  apiBaseUrl: (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "/api",
  dataMode: demoMode ? "mock" as const : dataMode(import.meta.env.VITE_DATA_MODE as string | undefined),
  /** Developer-only indicator of demo adapters and mocked services. Never shown in production. */
  showDevBadge: !demoMode && flag(import.meta.env.VITE_SHOW_DEV_BADGE as string | undefined, false),
  /** Simulated latency of mock services, so loading states are exercised. */
  mockLatencyMs: Number(import.meta.env.VITE_MOCK_LATENCY_MS ?? 380),
  requestTimeoutMs: 20_000,
  isDev: import.meta.env.DEV,
} as const;
