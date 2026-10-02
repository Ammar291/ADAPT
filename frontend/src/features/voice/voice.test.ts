import { describe, expect, it } from "vitest";
import { readActionOutcome, readRecordedDecision } from "./api";
import {
  conversationHistory,
  conversationReducer,
  derivePhase,
  initialConversation,
  type ConversationAction,
  type ConversationState,
  type TurnItem,
} from "./conversation";
import { audioProfileFor, reconnectDelay, ToolTurn } from "./orchestration";
import { parseServerEvent, type ServerEvent } from "./realtime/events";
import { selectActions, selectCitations, selectIsLive, selectPendingApprovals, selectRunningTool } from "./selectors";
import type { VoiceToolCallResult } from "./types";

function run(actions: ConversationAction[], from: ConversationState = initialConversation): ConversationState {
  return actions.reduce(conversationReducer, from);
}

const rt = (event: ServerEvent): ConversationAction => ({ type: "realtime", event });
const connected = run([{ type: "connection", state: "connected" }]);

function toolResult(overrides: Partial<VoiceToolCallResult> = {}): VoiceToolCallResult {
  return {
    call_id: "call_1",
    name: "prepare_action",
    status: "needs_approval",
    output: { status: "needs_approval" },
    activity: { call_id: "call_1", name: "prepare_action", label: "Preparing an action", status: "needs_approval", summary: "Prepared" },
    approval: {
      action_id: "act_1",
      title: "Continue on ICP",
      summary: "Opens ICP",
      consequences: [],
      requires_user_authentication: true,
      handoff_url: "https://icp.gov.ae",
      kind: "official_handoff",
      simulation_label: null,
    },
    consent: null,
    citations: [],
    ui_hint: null,
    ...overrides,
  };
}

describe("conversation reducer", () => {
  it("orders the person's turn before the reply, even when transcription arrives late", () => {
    const state = run(
      [
        rt({ type: "input_audio_buffer.speech_started", item_id: "u1" }),
        rt({ type: "input_audio_buffer.speech_stopped", item_id: "u1" }),
        rt({ type: "response.created", response: { id: "r1" } }),
        rt({ type: "response.output_audio_transcript.delta", response_id: "r1", item_id: "a1", delta: "مرحبا" }),
        rt({ type: "conversation.item.input_audio_transcription.completed", item_id: "u1", transcript: "Salam" }),
      ],
      connected,
    );
    const turns = state.items as TurnItem[];
    expect(turns.map((t) => [t.speaker, t.text])).toEqual([
      ["user", "Salam"],
      ["assistant", "مرحبا"],
    ]);
    expect(derivePhase(state)).toBe("thinking");
  });

  it("marks the assistant's turn as interrupted on barge-in", () => {
    const state = run(
      [
        rt({ type: "response.created", response: { id: "r1" } }),
        rt({ type: "output_audio_buffer.started", response_id: "r1" }),
        rt({ type: "response.output_audio_transcript.delta", response_id: "r1", item_id: "a1", delta: "The first step is" }),
        rt({ type: "input_audio_buffer.speech_started", item_id: "u2" }),
      ],
      connected,
    );
    const reply = state.items.find((i) => i.id === "turn:a1") as TurnItem;
    expect(reply.interrupted).toBe(true);
    expect(reply.final).toBe(true);
    expect(state.assistantSpeaking).toBe(false);
    expect(derivePhase(state)).toBe("user_speaking");

    // A late transcript delta from the cancelled response doesn't extend the stopped turn.
    const after = run(
      [rt({ type: "response.output_audio_transcript.delta", response_id: "r1", item_id: "a1", delta: " to…" })],
      state,
    );
    expect((after.items.find((i) => i.id === "turn:a1") as TurnItem).text).toBe("The first step is");
  });

  it("drops empty transcriptions (coughs, background noise)", () => {
    const state = run(
      [
        rt({ type: "input_audio_buffer.speech_started", item_id: "u1" }),
        rt({ type: "conversation.item.input_audio_transcription.completed", item_id: "u1", transcript: "  " }),
      ],
      connected,
    );
    expect(state.items).toEqual([]);
  });

  it("shows tool progress, then the approval card after the tool", () => {
    const running = run([{ type: "tool_started", callId: "call_1", name: "prepare_action", label: "Preparing an action" }], connected);
    expect(derivePhase(running)).toBe("tool");
    const done = run([{ type: "tool_finished", result: toolResult() }], running);
    expect(done.items.map((i) => i.kind)).toEqual(["tool", "approval"]);
    expect(done.runningTools).toEqual([]);
    const approved = run(
      [
        { type: "approval", id: "approval:act_1", state: "approved", outcome: { message: "Ready", handoffUrl: "https://icp.gov.ae" } },
      ],
      done,
    );
    expect(approved.items[1]).toMatchObject({ state: "approved", outcome: { handoffUrl: "https://icp.gov.ae" } });
  });

  it("adds a consent card when a tool needs opt-in", () => {
    const state = run(
      [
        {
          type: "tool_finished",
          result: toolResult({
            status: "needs_consent",
            approval: null,
            consent: { preference: "faith_personalization", title: "Include faith?", detail: "…" },
          }),
        },
      ],
      connected,
    );
    expect(state.items.map((i) => i.kind)).toEqual(["tool", "consent"]);
  });

  it("derives phases for every connection state and for text mode", () => {
    expect(derivePhase(initialConversation)).toBe("idle");
    expect(derivePhase(run([{ type: "connection", state: "reconnecting" }]))).toBe("reconnecting");
    expect(derivePhase(run([{ type: "muted", muted: true }], connected))).toBe("muted");
    expect(derivePhase(run([rt({ type: "output_audio_buffer.started" })], connected))).toBe("speaking");
    const text = run([{ type: "mode", mode: "text" }, { type: "responding", responding: true }]);
    expect(derivePhase(text)).toBe("thinking");
  });

  it("keeps finished turns as history for text and for restoring a call", () => {
    const state = run(
      [
        { type: "turn", id: "t1", speaker: "user", text: "I want to bring my wife", channel: "text" },
        rt({ type: "response.output_audio_transcript.delta", response_id: "r", item_id: "a1", delta: "Half-finished" }),
        { type: "turn", id: "t2", speaker: "assistant", text: "You'll need the family visa.", channel: "text" },
        { type: "notice", id: "n", text: "Reconnected" },
      ],
      connected,
    );
    expect(conversationHistory(state.items)).toEqual([
      { role: "user", text: "I want to bring my wife" },
      { role: "assistant", text: "You'll need the family visa." },
    ]);
  });
});

describe("ToolTurn", () => {
  it("continues once every call of the response has an output", () => {
    const turn = new ToolTurn();
    turn.responseStarted();
    expect(turn.begin("a")).toBe(true);
    expect(turn.begin("b")).toBe(true);
    expect(turn.begin("a")).toBe(false); // repeated event
    expect(turn.finish("a")).toBe(false);
    expect(turn.responseDone()).toBe(false); // "b" still running
    expect(turn.finish("b")).toBe(true);
  });

  it("waits for the response to end even if outputs are quick", () => {
    const turn = new ToolTurn();
    turn.responseStarted();
    turn.begin("a");
    expect(turn.finish("a")).toBe(false);
    expect(turn.responseDone()).toBe(true);
  });

  it("lets the person's new turn drive the next response instead", () => {
    const turn = new ToolTurn();
    turn.responseStarted();
    turn.begin("a");
    turn.responseDone();
    turn.userSpeech();
    expect(turn.finish("a")).toBe(false);
  });

  it("does nothing for responses without tool calls", () => {
    const turn = new ToolTurn();
    turn.responseStarted();
    expect(turn.responseDone()).toBe(false);
  });
});

describe("helpers", () => {
  it("backs off exponentially with a ceiling", () => {
    const fixed = () => 0.5;
    expect([1, 2, 3, 4, 5, 9].map((n) => reconnectDelay(n, fixed))).toEqual([1000, 2000, 4000, 8000, 15000, 15000]);
  });

  it("picks near-field noise reduction for headsets and phones", () => {
    expect(audioProfileFor(["AirPods Pro"], false)).toBe("near_field");
    expect(audioProfileFor(["MacBook Pro Microphone"], false)).toBe("far_field");
    expect(audioProfileFor(["Default"], true)).toBe("near_field");
  });

  it("parses known Realtime events and ignores the rest", () => {
    expect(parseServerEvent('{"type":"input_audio_buffer.speech_started","item_id":"x"}')?.type).toBe(
      "input_audio_buffer.speech_started",
    );
    expect(parseServerEvent('{"type":"response.output_audio.delta","delta":"…"}')).toBeNull();
    expect(parseServerEvent("not json")).toBeNull();
    expect(parseServerEvent(new ArrayBuffer(2))).toBeNull();
  });

  it("reads a decision already recorded elsewhere", () => {
    expect(readRecordedDecision({ status: "handoff_required", approval: { status: "approved" } })).toBe("approved");
    expect(readRecordedDecision({ status: "rejected", approval: { status: "rejected" } })).toBe("declined");
    expect(readRecordedDecision({ status: "awaiting_approval", approval: { status: "pending" } })).toBeNull();
  });

  it("only trusts https handoff links from an approval response", () => {
    expect(readActionOutcome({ action: { status: "handoff_ready", handoff_url: "https://icp.gov.ae" } })).toEqual({
      status: "handoff_ready",
      message: null,
      handoffUrl: "https://icp.gov.ae",
    });
    expect(readActionOutcome({ handoff_url: "javascript:alert(1)" }).handoffUrl).toBeNull();
    expect(
      readActionOutcome({ action: { status: "handoff_required", official_url: "https://icp.gov.ae/x" }, message: "Ready" }),
    ).toEqual({ status: "handoff_required", message: "Ready", handoffUrl: "https://icp.gov.ae/x" });
    expect(readActionOutcome(null)).toEqual({ status: null, message: null, handoffUrl: null });
  });
});

describe("selectors", () => {
  const withSources = run(
    [
      { type: "tool_started", callId: "s1", name: "retrieve_evidence", label: "Checking official sources" },
      {
        type: "tool_finished",
        result: toolResult({
          call_id: "s1",
          name: "retrieve_evidence",
          status: "ok",
          approval: null,
          citations: [
            { title: "Sponsoring family", url: "https://u.ae/family", authority: "u.ae", retrieved_at: "2026-09-29T00:00:00Z", kind: "official_guidance" },
          ],
        }),
      },
      { type: "tool_finished", result: toolResult() },
      { type: "tool_started", callId: "s2", name: "get_journey", label: "Checking your plan" },
    ],
    connected,
  );

  it("lists sources once each, with their trust tier", () => {
    expect(selectCitations(withSources)).toEqual([
      {
        title: "Sponsoring family",
        url: "https://u.ae/family",
        authority: "u.ae",
        retrievedAt: "2026-09-29T00:00:00Z",
        section: null,
        quote: null,
        kind: "official_guidance",
      },
    ]);
  });

  it("finds the running tool and pending approvals", () => {
    expect(selectRunningTool(withSources)?.name).toBe("get_journey");
    expect(selectPendingApprovals(withSources).map((a) => a.request.action_id)).toEqual(["act_1"]);
  });

  it("reports actions, with the handoff only after the backend confirmed", () => {
    const approved = run(
      [{ type: "approval", id: "approval:act_1", state: "approved", outcome: { message: "Ready", handoffUrl: "https://icp.gov.ae" } }],
      withSources,
    );
    const actions = selectActions(approved);
    expect(actions.find((a) => a.kind === "approval")).toMatchObject({ status: "approved", handoffUrl: "https://icp.gov.ae" });
    expect(selectActions(withSources).some((a) => a.kind === "approval")).toBe(false);
    expect(selectIsLive(approved)).toBe(true);
  });
});

describe("selector stability", () => {
  it("returns the same list until the conversation changes (safe for useVoiceStore)", () => {
    const state = run([{ type: "tool_finished", result: toolResult() }], connected);
    expect(selectPendingApprovals(state)).toBe(selectPendingApprovals({ ...state }));
    expect(selectCitations(state)).toBe(selectCitations(state));
    expect(selectActions(state)).toBe(selectActions({ ...state, muted: true }));
    const next = run([{ type: "notice", id: "n", text: "x" }], state);
    expect(selectActions(next)).not.toBe(selectActions(state));
  });
});

describe("review fixes", () => {
  it("does not answer twice when the person's own turn starts a response during tool work", () => {
    const turn = new ToolTurn();
    turn.responseStarted();
    turn.begin("a");
    expect(turn.responseDone()).toBe(false);
    turn.responseStarted(); // voice activity detection answered the person
    expect(turn.finish("a")).toBe(false);
    expect(turn.responseDone()).toBe(false);
    // …and the next ordinary tool turn continues normally.
    turn.responseStarted();
    turn.begin("b");
    turn.finish("b");
    expect(turn.responseDone()).toBe(true);
  });

  it("stops ADAPT's turn when the person types over it", () => {
    const speaking = run(
      [
        rt({ type: "response.created", response: { id: "r1" } }),
        rt({ type: "output_audio_buffer.started" }),
        rt({ type: "response.output_audio_transcript.delta", response_id: "r1", item_id: "a1", delta: "First you" }),
        { type: "interrupt" },
      ],
      connected,
    );
    expect(speaking.items[0]).toMatchObject({ interrupted: true, final: true });
    expect(derivePhase(speaking)).toBe("listening");
  });

  it("trims history to what the API accepts", () => {
    const long = run([{ type: "turn", id: "t", speaker: "assistant", text: "x".repeat(5000), channel: "text" }]);
    expect(conversationHistory(long.items)[0]?.text.length).toBe(4000);
  });
});
