/**
 * Conversation state shared by voice and text (pure, framework-free, unit tested).
 *
 * Voice and text write to one conversation, so switching modes, or reconnecting after a
 * dropped call, keeps the context. Nothing here is persisted: transcripts live in memory
 * for the page session only.
 */
import type { ApprovalRequest, ConsentRequest, ToolCitation, ToolStatus, VoiceToolCallResult } from "./types";
import type { ServerEvent } from "./realtime/events";

export type Speaker = "user" | "assistant";
export type Channel = "voice" | "text";

export interface TurnItem {
  kind: "turn";
  id: string;
  speaker: Speaker;
  text: string;
  final: boolean;
  interrupted: boolean;
  channel: Channel;
}

export interface ToolItem {
  kind: "tool";
  id: string;
  callId: string;
  name: string;
  label: string;
  status: "running" | ToolStatus;
  summary: string | null;
  uiHint: string | null;
  /** Sources behind the result, each with its trust tier. */
  citations: ToolCitation[];
}

export type ApprovalState = "pending" | "submitting" | "approved" | "declined" | "failed";

export interface ApprovalOutcome {
  message: string;
  handoffUrl: string | null;
}

export interface ApprovalItem {
  kind: "approval";
  id: string;
  request: ApprovalRequest;
  state: ApprovalState;
  outcome: ApprovalOutcome | null;
  /** Where the decision is recorded: the actions API, or the frontend mock services. */
  via: "actions" | "mock";
}

export type ConsentState = "pending" | "saving" | "granted" | "declined" | "failed";

export interface ConsentItem {
  kind: "consent";
  id: string;
  request: ConsentRequest;
  state: ConsentState;
}

export interface NoticeItem {
  kind: "notice";
  id: string;
  text: string;
  tone: "info" | "warning";
}

export type ConversationItem = TurnItem | ToolItem | ApprovalItem | ConsentItem | NoticeItem;

export type ConnectionState =
  | "idle"
  | "requesting_mic"
  | "connecting"
  | "connected"
  | "reconnecting"
  | "offline"
  | "ended"
  | "failed";

export type Mode = "voice" | "text";

export type ProblemCode =
  | "mic_denied"
  | "mic_missing"
  | "mic_busy"
  | "insecure_context"
  | "unsupported"
  | "voice_unavailable"
  | "connect_timeout"
  | "connect_failed"
  | "connection_lost"
  | "session_expired"
  | "rate_limited"
  | "assistant_error";

export interface Problem {
  code: ProblemCode;
  title: string;
  detail: string;
  canRetry: boolean;
}

export interface ConversationState {
  items: ConversationItem[];
  connection: ConnectionState;
  mode: Mode;
  muted: boolean;
  userSpeaking: boolean;
  assistantSpeaking: boolean;
  responding: boolean;
  runningTools: string[];
  problem: Problem | null;
}

export const initialConversation: ConversationState = {
  items: [],
  connection: "idle",
  mode: "voice",
  muted: false,
  userSpeaking: false,
  assistantSpeaking: false,
  responding: false,
  runningTools: [],
  problem: null,
};

export type Phase =
  | "idle"
  | "requesting_mic"
  | "connecting"
  | "reconnecting"
  | "offline"
  | "ended"
  | "failed"
  | "listening"
  | "muted"
  | "user_speaking"
  | "thinking"
  | "tool"
  | "speaking"
  | "text";

/** What the orb and status line show. Activity wins over rest states. */
export function derivePhase(state: ConversationState): Phase {
  if (state.mode === "text") {
    if (state.runningTools.length) return "tool";
    return state.responding ? "thinking" : "text";
  }
  if (state.connection !== "connected") return state.connection;
  if (state.userSpeaking) return "user_speaking";
  if (state.runningTools.length) return "tool";
  if (state.assistantSpeaking) return "speaking";
  if (state.responding) return "thinking";
  return state.muted ? "muted" : "listening";
}

export type ConversationAction =
  | { type: "realtime"; event: ServerEvent }
  | { type: "connection"; state: ConnectionState }
  | { type: "mode"; mode: Mode }
  | { type: "muted"; muted: boolean }
  | { type: "problem"; problem: Problem | null }
  | { type: "responding"; responding: boolean }
  | { type: "turn"; id: string; speaker: Speaker; text: string; channel: Channel }
  | { type: "tool_started"; callId: string; name: string; label: string }
  | { type: "tool_finished"; result: VoiceToolCallResult }
  | { type: "approval_request"; request: ApprovalRequest; via: "actions" | "mock" }
  | { type: "approval"; id: string; state: ApprovalState; outcome?: ApprovalOutcome | null }
  | { type: "consent"; id: string; state: ConsentState }
  | { type: "notice"; id: string; text: string; tone?: "info" | "warning" }
  | { type: "interrupt" }
  | { type: "audio_reset" }
  | { type: "clear" };

const turnKey = (id: string) => `turn:${id}`;

function upsertTurn(
  items: ConversationItem[],
  id: string,
  speaker: Speaker,
  update: (turn: TurnItem) => TurnItem,
): ConversationItem[] {
  const key = turnKey(id);
  const index = items.findIndex((item) => item.id === key);
  if (index === -1) {
    const turn: TurnItem = { kind: "turn", id: key, speaker, text: "", final: false, interrupted: false, channel: "voice" };
    return [...items, update(turn)];
  }
  const next = items.slice();
  next[index] = update(items[index] as TurnItem);
  return next;
}

function removeItem(items: ConversationItem[], id: string): ConversationItem[] {
  return items.filter((item) => item.id !== id);
}

/** Barge-in: the assistant's unfinished turn stops where the person cut in. */
function interruptAssistant(items: ConversationItem[]): ConversationItem[] {
  return items.map((item) =>
    item.kind === "turn" && item.speaker === "assistant" && !item.final
      ? { ...item, final: true, interrupted: true }
      : item,
  );
}

function reduceRealtime(state: ConversationState, event: ServerEvent): ConversationState {
  switch (event.type) {
    case "session.created":
      return { ...state, connection: "connected", problem: null };
    case "input_audio_buffer.speech_started": {
      const bargeIn = state.assistantSpeaking || state.responding;
      const items = bargeIn ? interruptAssistant(state.items) : state.items;
      return {
        ...state,
        userSpeaking: true,
        assistantSpeaking: false,
        responding: bargeIn ? false : state.responding,
        items: upsertTurn(items, event.item_id, "user", (turn) => turn),
      };
    }
    case "input_audio_buffer.speech_stopped":
      return { ...state, userSpeaking: false };
    case "conversation.item.input_audio_transcription.delta":
      return {
        ...state,
        items: upsertTurn(state.items, event.item_id, "user", (turn) => ({
          ...turn,
          text: turn.text + (event.delta ?? ""),
        })),
      };
    case "conversation.item.input_audio_transcription.completed": {
      const text = event.transcript.trim();
      if (!text) return { ...state, items: removeItem(state.items, turnKey(event.item_id)) };
      return {
        ...state,
        items: upsertTurn(state.items, event.item_id, "user", (turn) => ({ ...turn, text, final: true })),
      };
    }
    case "conversation.item.input_audio_transcription.failed": {
      const key = turnKey(event.item_id);
      const existing = state.items.find((item) => item.id === key) as TurnItem | undefined;
      if (!existing?.text) return { ...state, items: removeItem(state.items, key) };
      return { ...state, items: upsertTurn(state.items, event.item_id, "user", (t) => ({ ...t, final: true })) };
    }
    case "response.created":
      return { ...state, responding: true };
    case "response.output_audio_transcript.delta":
    case "response.output_text.delta":
      return {
        ...state,
        responding: true,
        items: upsertTurn(state.items, event.item_id, "assistant", (turn) =>
          turn.final ? turn : { ...turn, text: turn.text + event.delta },
        ),
      };
    case "response.output_audio_transcript.done":
    case "response.output_text.done": {
      const text = event.type === "response.output_text.done" ? event.text : event.transcript;
      return {
        ...state,
        items: upsertTurn(state.items, event.item_id, "assistant", (turn) =>
          turn.interrupted ? turn : { ...turn, text: text || turn.text, final: true },
        ),
      };
    }
    case "response.done": {
      const cancelled = event.response.status === "cancelled";
      const ids = new Set((event.response.output ?? []).map((item) => item.id && turnKey(item.id)));
      const items = state.items.map((item) =>
        item.kind === "turn" && item.speaker === "assistant" && ids.has(item.id) && !item.final
          ? { ...item, final: true, interrupted: cancelled }
          : item,
      );
      return { ...state, responding: false, items };
    }
    case "output_audio_buffer.started":
      return { ...state, assistantSpeaking: true };
    case "output_audio_buffer.stopped":
    case "output_audio_buffer.cleared":
      return { ...state, assistantSpeaking: false };
    default:
      return state;
  }
}

export function conversationReducer(state: ConversationState, action: ConversationAction): ConversationState {
  switch (action.type) {
    case "realtime":
      return reduceRealtime(state, action.event);
    case "connection":
      return {
        ...state,
        connection: action.state,
        ...(action.state === "connected" ? {} : { userSpeaking: false, assistantSpeaking: false }),
      };
    case "mode":
      return { ...state, mode: action.mode, userSpeaking: false, assistantSpeaking: false };
    case "muted":
      return { ...state, muted: action.muted };
    case "problem":
      return { ...state, problem: action.problem };
    case "responding":
      return { ...state, responding: action.responding };
    case "turn":
      return {
        ...state,
        items: [
          ...state.items,
          {
            kind: "turn",
            id: turnKey(action.id),
            speaker: action.speaker,
            text: action.text,
            final: true,
            interrupted: false,
            channel: action.channel,
          },
        ],
      };
    case "tool_started": {
      const id = `tool:${action.callId}`;
      if (state.items.some((item) => item.id === id)) return state;
      const tool: ToolItem = {
        kind: "tool",
        id,
        callId: action.callId,
        name: action.name,
        label: action.label,
        status: "running",
        summary: null,
        uiHint: null,
        citations: [],
      };
      return {
        ...state,
        items: [...state.items, tool],
        runningTools: [...state.runningTools, action.callId],
      };
    }
    case "tool_finished": {
      const { result } = action;
      const id = `tool:${result.call_id}`;
      const finished: ToolItem = {
        kind: "tool",
        id,
        callId: result.call_id,
        name: result.name,
        label: result.activity.label,
        status: result.status,
        summary: result.activity.summary ?? null,
        uiHint: result.ui_hint ?? null,
        citations: result.citations ?? [],
      };
      const extras: ConversationItem[] = [];
      if (result.approval) {
        extras.push({
          kind: "approval",
          id: `approval:${result.approval.action_id}`,
          request: result.approval,
          state: "pending",
          outcome: null,
          via: "actions",
        });
      }
      if (result.consent) {
        extras.push({ kind: "consent", id: `consent:${result.call_id}`, request: result.consent, state: "pending" });
      }
      const index = state.items.findIndex((item) => item.id === id);
      const items =
        index === -1
          ? [...state.items, finished, ...extras]
          : [...state.items.slice(0, index), finished, ...extras, ...state.items.slice(index + 1)];
      return { ...state, items, runningTools: state.runningTools.filter((c) => c !== result.call_id) };
    }
    case "approval_request": {
      const id = `approval:${action.request.action_id}`;
      if (state.items.some((item) => item.id === id)) return state;
      const item: ApprovalItem = { kind: "approval", id, request: action.request, state: "pending", outcome: null, via: action.via };
      return { ...state, items: [...state.items, item] };
    }
    case "approval":
      return {
        ...state,
        items: state.items.map((item) =>
          item.kind === "approval" && item.id === action.id
            ? { ...item, state: action.state, outcome: action.outcome ?? item.outcome }
            : item,
        ),
      };
    case "consent":
      return {
        ...state,
        items: state.items.map((item) =>
          item.kind === "consent" && item.id === action.id ? { ...item, state: action.state } : item,
        ),
      };
    case "notice":
      return {
        ...state,
        items: [...state.items, { kind: "notice", id: `notice:${action.id}`, text: action.text, tone: action.tone ?? "info" }],
      };
    case "interrupt":
      return { ...state, items: interruptAssistant(state.items), assistantSpeaking: false, responding: false };
    case "audio_reset":
      return { ...state, userSpeaking: false, assistantSpeaking: false, responding: false, runningTools: [] };
    case "clear":
      return { ...initialConversation, mode: state.mode };
  }
}

/** The API accepts messages of up to this many characters. */
export const MAX_MESSAGE_CHARS = 4000;

/** Finished turns as plain messages: context for the text assistant or a restored call. */
export function conversationHistory(
  items: ConversationItem[],
  limit = 24,
): Array<{ role: Speaker; text: string }> {
  const turns = items.filter(
    (item): item is TurnItem => item.kind === "turn" && item.text.trim().length > 0 && (item.final || item.interrupted),
  );
  return turns.slice(-limit).map((turn) => {
    const text = turn.text.trim();
    return { role: turn.speaker, text: text.length > MAX_MESSAGE_CHARS ? `${text.slice(0, MAX_MESSAGE_CHARS - 1)}…` : text };
  });
}
