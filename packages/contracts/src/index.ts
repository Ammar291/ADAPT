/**
 * @adapt/contracts — typed API contracts shared by every frontend workstream.
 *
 * Source of truth: Pydantic models in `backend/app/contracts` → OpenAPI →
 * `src/generated/openapi.ts` (generated; never edit by hand). Regenerate with
 * `npm run contracts:generate` from the repository root. A backend test fails when the
 * committed `openapi.json` is stale.
 *
 * This file only adds ergonomic aliases and tiny pure helpers on top of the generated
 * types. Business logic belongs in the backend.
 */

export * from "./generated/openapi";
import type { components, paths } from "./generated/openapi";

export type { components, paths };
export type Schemas = components["schemas"];

// --- agent events -------------------------------------------------------------------

import type { AgentEvent } from "./generated/openapi";

export type AgentEventType = AgentEvent["event"];

/** Narrow an `AgentEvent` union member by its `event` discriminator. */
export type EventOf<T extends AgentEventType> = Extract<AgentEvent, { event: T }>;

export const TERMINAL_EVENT_TYPES = ["run_completed", "run_failed", "run_cancelled"] as const;
export type TerminalEventType = (typeof TERMINAL_EVENT_TYPES)[number];

export function isTerminalEvent(event: AgentEvent): event is EventOf<TerminalEventType> {
  return (TERMINAL_EVENT_TYPES as readonly string[]).includes(event.event);
}

export function isEventOfType<T extends AgentEventType>(
  event: AgentEvent,
  type: T,
): event is EventOf<T> {
  return event.event === type;
}

// --- errors ---------------------------------------------------------------------------

import type { ProblemDetail } from "./generated/openapi";

export function isProblemDetail(value: unknown): value is ProblemDetail {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as ProblemDetail).status === "number" &&
    typeof (value as ProblemDetail).code === "string" &&
    typeof (value as ProblemDetail).title === "string"
  );
}

// --- API paths ----------------------------------------------------------------------------

/** Every documented API path, e.g. "/api/agents/{run_id}". */
export type ApiPath = keyof paths;

/** JSON body of a successful response for `method` on `path`. */
export type ApiResponse<
  P extends ApiPath,
  M extends keyof paths[P] & ("get" | "post" | "patch" | "put" | "delete"),
> = paths[P][M] extends {
  responses: infer R;
}
  ? R extends { 200: { content: { "application/json": infer B } } }
    ? B
    : R extends { 201: { content: { "application/json": infer B } } }
      ? B
      : R extends { 202: { content: { "application/json": infer B } } }
        ? B
        : void
  : never;
