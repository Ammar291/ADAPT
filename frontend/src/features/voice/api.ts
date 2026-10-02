/**
 * Voice and assistant endpoints. Components never call these directly; the controller does.
 */
import type { UserOut } from "@adapt/contracts";
import { api } from "@/lib/api/client";
import type {
  AssistantMessageOut,
  AssistantMessageRequest,
  VoiceSessionOut,
  VoiceSessionRequest,
  VoiceToolCallRequest,
  VoiceToolCallResult,
} from "./types";

export const voiceApi = {
  createSession: (body: VoiceSessionRequest) =>
    api.post<VoiceSessionOut>("/voice/session", body, { timeoutMs: 12_000 }),
  runToolCall: (body: VoiceToolCallRequest) =>
    api.post<VoiceToolCallResult>("/voice/tool-calls", body, { timeoutMs: 30_000 }),
  assistantTurn: (body: AssistantMessageRequest) =>
    api.post<AssistantMessageOut>("/voice/assistant", body, { timeoutMs: 60_000 }),
  approveAction: (actionId: string) =>
    api.post<unknown>(`/actions/${encodeURIComponent(actionId)}/approve`, {}),
  rejectAction: (actionId: string) =>
    api.post<unknown>(`/actions/${encodeURIComponent(actionId)}/reject`, {}),
  getAction: (actionId: string) => api.get<unknown>(`/actions/${encodeURIComponent(actionId)}`),
  setConsent: (preference: string, status: "granted" | "declined") =>
    api.patch<UserOut>("/me/preferences", { [preference]: status }),
};

/** The decision already recorded on an action (e.g. decided elsewhere), or null if none. */
export function readRecordedDecision(body: unknown): "approved" | "declined" | null {
  const action = (typeof body === "object" && body !== null ? body : {}) as Record<string, unknown>;
  const approval = (typeof action.approval === "object" && action.approval !== null ? action.approval : {}) as Record<
    string,
    unknown
  >;
  if (approval.status === "approved") return "approved";
  if (approval.status === "rejected") return "declined";
  if (action.status === "rejected" || action.status === "cancelled") return "declined";
  if (["approved", "handoff_required", "submitted", "completed"].includes(String(action.status))) return "approved";
  return null;
}

/** Read what the backend confirmed after an approval, whatever the exact action shape. */
export function readActionOutcome(body: unknown): { status: string | null; message: string | null; handoffUrl: string | null } {
  const root = (typeof body === "object" && body !== null ? body : {}) as Record<string, unknown>;
  const action = (typeof root.action === "object" && root.action !== null ? root.action : root) as Record<
    string,
    unknown
  >;
  const text = (value: unknown) => (typeof value === "string" && value.trim() ? value : null);
  // The journey agent returns the official page as `official_url`; older shapes used `handoff_url`.
  const url = text(action.official_url) ?? text(action.handoff_url) ?? text(root.handoff_url);
  const reportedStatus = text(action.status);
  const externalStatus = reportedStatus === "submitted" || reportedStatus === "completed";
  const verified = action.confirmation_source === "adapter" && action.is_simulated !== true && text(action.external_reference) !== null;
  return {
    status: externalStatus && !verified ? (url ? "handoff_required" : "prepared") : reportedStatus,
    message: externalStatus && !verified ? null : text(action.message) ?? text(root.message),
    handoffUrl: url?.startsWith("https://") ? url : null,
  };
}
