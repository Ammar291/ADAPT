import type { Citation, EvidenceKind } from "./common";
import type { ActionRecord, Approval } from "./documents";

export type AssistantState = "idle" | "connecting" | "listening" | "thinking" | "speaking" | "error";

export interface AssistantCitation extends Citation {
  kind: EvidenceKind;
}

export interface ToolCall {
  id: string;
  /** Machine name, e.g. `get_journey_status`. */
  name: string;
  /** What the user sees, e.g. "Checking your journey". */
  label: string;
  args: Record<string, unknown>;
  status: "running" | "done" | "failed";
  resultSummary: string | null;
}

/**
 * One stream vocabulary for typed chat and voice. The mock engine and the realtime voice
 * client both produce these events; the conversation store folds them into turns.
 */
export type AssistantEvent =
  | { type: "state"; state: AssistantState; detail?: string }
  | { type: "user_transcript"; turnId: string; text: string; final: boolean }
  | { type: "turn_started"; turnId: string }
  | { type: "text_delta"; turnId: string; text: string }
  | { type: "tool_call"; turnId: string; call: ToolCall }
  | { type: "tool_result"; turnId: string; callId: string; summary: string; ok: boolean }
  | { type: "citation"; turnId: string; citation: AssistantCitation }
  | { type: "action"; turnId: string; action: ActionRecord }
  | { type: "approval"; turnId: string; approval: Approval }
  | { type: "navigate"; turnId: string; to: string; label: string }
  | { type: "turn_completed"; turnId: string }
  | { type: "error"; message: string };

export interface AssistantContext {
  /** The screen the user is on, so answers can be about what they see. */
  route: string;
  channel: "text" | "voice";
  language: string;
}

export interface AssistantTurn {
  id: string;
  role: "user" | "assistant";
  text: string;
  channel: "text" | "voice";
  pending: boolean;
  toolCalls: ToolCall[];
  citations: AssistantCitation[];
  actions: ActionRecord[];
  approvals: Approval[];
  links: { to: string; label: string }[];
  createdAt: string;
}
