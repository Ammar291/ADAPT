import { tr } from "@/i18n";
/**
 * The voice session controller: one per page, independent of React, so a conversation keeps
 * running when the sheet is minimised.
 *
 * Responsibilities: microphone and permissions, minting a session on ADAPT's backend,
 * the WebRTC call, forwarding tool calls to the backend and results back to the model,
 * barge-in bookkeeping, reconnecting with the conversation restored, the text fallback,
 * and relaying the user's approval and consent decisions (made only by tapping in the UI).
 */
import type { UserOut } from "@adapt/contracts";
import { queryClient } from "@/app/providers";
import { ApiError, describeError } from "@/lib/api/errors";
import { queryKeys, TOPIC_KEYS } from "@/lib/api/queryKeys";
import { readActionOutcome, readRecordedDecision, voiceApi } from "./api";
import {
  acquireMicrophone,
  detectAudioProfile,
  LevelMeter,
  MicrophoneError,
  ScreenWakeLock,
  setMediaSession,
} from "./audio";
import { conversationHistory, type ApprovalItem, type ConsentItem, type Problem, type ProblemCode } from "./conversation";
import { decideMockApproval, mockAssistantActive, runMockTurn } from "./mockBridge";
import { MAX_RECONNECT_ATTEMPTS, reconnectDelay, ToolTurn } from "./orchestration";
import { problem } from "./problems";
import { ConnectError, RealtimeConnection } from "./realtime/connection";
import type { ClientEvent, FunctionCallItem, ServerEvent } from "./realtime/events";
import { conversation, dispatch } from "./store";
import type { AudioProfile, VoiceSessionOut, VoiceToolCallResult } from "./types";

const CONNECT_TIMEOUT_MS = 15_000;
/** Connection states in which a call exists or is being set up. */
const IN_CALL = new Set(["requesting_mic", "connecting", "connected", "reconnecting", "offline"]);
/** Harmless protocol races (e.g. cancelling a response that just finished). */
const IGNORED_ERRORS = new Set([
  "conversation_already_has_active_response",
  "response_cancel_not_active",
  "input_audio_buffer_commit_empty",
]);

/** Server state a tool may have changed: screens showing it refetch (the server is the truth). */
const TOOL_TOPICS: Record<string, string[]> = {
  start_journey: ["journeys", "runs"],
  prepare_action: ["approvals", "journeys"],
  start_research: ["discover", "runs"],
  simulate_journey: ["journeys", "runs"],
};

function refresh(topics: string[]): void {
  for (const topic of topics) for (const key of TOPIC_KEYS[topic] ?? []) void queryClient.invalidateQueries({ queryKey: key });
}

function refreshAfterTool(result: VoiceToolCallResult): void {
  if (result.status === "ok" || result.status === "needs_approval") refresh(TOOL_TOPICS[result.name] ?? []);
}

function newId(prefix: string): string {
  return `${prefix}_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`;
}

function preferredLanguage(): string | null {
  const me = queryClient.getQueryData<UserOut>(queryKeys.me);
  return me?.preferences.preferred_language ?? (typeof navigator !== "undefined" ? navigator.language : null);
}

/** App-side facts quote titles that may come from other systems: keep them inert. */
function quoteTitle(title: string): string {
  return `"${title.replace(/[\r\n"“”]+/g, " ").trim().slice(0, 120)}"`;
}

function httpsOnly(url: string | null | undefined): string | null {
  return url && url.startsWith("https://") ? url : null;
}

function stopStream(stream: MediaStream | null): void {
  stream?.getTracks().forEach((track) => track.stop());
}

function apiProblem(error: unknown): ProblemCode {
  if (error instanceof ApiError) {
    if (error.status === 401) return "session_expired";
    if (error.status === 429 || error.code === "voice_busy") return "rate_limited";
    if (error.code === "timeout") return "connect_timeout";
  }
  return "connect_failed";
}

function failedToolResult(callId: string, name: string, label: string, error: unknown): VoiceToolCallResult {
  const ended = error instanceof ApiError && error.code === "voice_session_invalid";
  const guidance = ended
    ? tr("copy.this_voice_session_has_ended_tell_the_person_to__651c6ba")
    : error instanceof ApiError && error.status === 429
      ? tr("copy.too_many_requests_in_a_short_time_ask_the_person_082cfff")
      : tr("copy.the_app_couldn_t_reach_adapt_to_do_this_tell_the_ef5aa57");
  return {
    call_id: callId,
    name,
    status: "error",
    output: { status: "error", guidance },
    activity: { call_id: callId, name, label, status: "error", summary: tr("copy.couldn_t_complete_this_eff9b2a") },
    approval: null,
    consent: null,
    citations: [],
    ui_hint: null,
  };
}

class VoiceController {
  /** Bumped whenever a session ends or restarts; stale async work checks it and stops. */
  private generation = 0;
  private connection: RealtimeConnection | null = null;
  private session: VoiceSessionOut | null = null;
  private labels = new Map<string, string>();
  private readonly toolTurn = new ToolTurn();
  private mic: MediaStream | null = null;
  private attempt = 0;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private context: AudioContext | null = null;
  private micMeter: LevelMeter | null = null;
  private outMeter: LevelMeter | null = null;
  private audioElement: HTMLAudioElement | null = null;
  private readonly wakeLock = new ScreenWakeLock();
  private profile: AudioProfile = "near_field";
  private attached = false;
  /** A message typed while the call was connecting: answered once it's up. */
  private pendingReply = false;
  private recovering = false;
  /** Bumped by "new conversation" so late text replies don't land in the new one. */
  private epoch = 0;

  // --- public API -------------------------------------------------------------------------

  /** Start talking. Must be called from a user gesture (audio unlock on mobile). */
  async startVoice(): Promise<void> {
    const gen = ++this.generation;
    this.teardown();
    this.attach();
    this.primeAudio();
    this.attempt = 0;
    dispatch({ type: "mode", mode: "voice" });
    dispatch({ type: "problem", problem: null });
    dispatch({ type: "connection", state: "requesting_mic" });

    let mic: MediaStream;
    try {
      mic = await acquireMicrophone();
    } catch (error) {
      if (gen !== this.generation) return;
      this.fallBackToText(problem(error instanceof MicrophoneError ? error.code : "mic_busy"));
      return;
    }
    if (gen !== this.generation) return stopStream(mic);
    this.useMicrophone(gen, mic);
    await this.connect(gen, false);
  }

  endVoice(): void {
    this.generation++;
    this.teardown();
    dispatch({ type: "connection", state: conversation().items.length ? "ended" : "idle" });
  }

  /** Releases everything a call holds. Every exit path goes through here. */
  private teardown(): void {
    this.clearRetry();
    this.connection?.close();
    this.connection = null;
    this.session = null;
    this.pendingReply = false;
    this.toolTurn.reset();
    this.releaseMedia();
    void this.wakeLock.release();
    setMediaSession(false, this.mediaHandlers);
    dispatch({ type: "audio_reset" });
  }

  toggleMute(): void {
    const muted = !conversation().muted;
    this.mic?.getAudioTracks().forEach((track) => (track.enabled = !muted));
    dispatch({ type: "muted", muted });
  }

  /** Switch to typing. Ends any call; the conversation carries over. */
  useText(): void {
    if (this.mic || this.connection || IN_CALL.has(conversation().connection)) this.endVoice();
    dispatch({ type: "mode", mode: "text" });
  }

  retry(): void {
    void this.startVoice();
  }

  newConversation(): void {
    this.epoch++;
    this.endVoice();
    dispatch({ type: "clear" });
    dispatch({ type: "connection", state: "idle" });
  }

  get active(): boolean {
    return this.mic !== null;
  }

  /** Loudness for the orb, 0–1. Cheap enough to call every animation frame. */
  levels(): { input: number; output: number } {
    if (!this.outMeter && this.context && this.connection?.remoteStream) {
      try {
        this.outMeter = new LevelMeter(this.context, this.connection.remoteStream);
      } catch {
        /* the orb falls back to its idle animation */
      }
    }
    const muted = conversation().muted;
    return { input: muted ? 0 : (this.micMeter?.level() ?? 0), output: this.outMeter?.level() ?? 0 };
  }

  async sendText(text: string): Promise<void> {
    const message = text.trim();
    if (!message) return;
    const id = newId("typed");
    const state = conversation();

    if (state.mode === "voice" && IN_CALL.has(state.connection)) {
      dispatch({ type: "turn", id, speaker: "user", text: message, channel: "text" });
      if (!this.connection?.isOpen) {
        // Connecting or reconnecting: the turn is re-added with the conversation when the
        // call is up, and answered then. Typing never ends the call.
        this.pendingReply = true;
        return;
      }
      if (state.responding || state.assistantSpeaking) {
        // Typing over ADAPT interrupts it, like speaking does.
        this.send({ type: "response.cancel" });
        this.send({ type: "output_audio_buffer.clear" });
        dispatch({ type: "interrupt" });
      }
      this.send({
        type: "conversation.item.create",
        item: { type: "message", role: "user", content: [{ type: "input_text", text: message }] },
      });
      this.send({ type: "response.create" });
      return;
    }

    if (state.mode !== "text") this.useText();
    const epoch = this.epoch;
    dispatch({ type: "turn", id, speaker: "user", text: message, channel: "text" });
    dispatch({ type: "responding", responding: true });
    try {
      if (mockAssistantActive()) {
        const text = await runMockTurn(id, message, preferredLanguage());
        if (text && epoch === this.epoch) {
          dispatch({ type: "turn", id: newId("reply"), speaker: "assistant", text, channel: "text" });
        }
        return;
      }
      const reply = await voiceApi.assistantTurn({
        messages: conversationHistory(conversation().items),
        language: preferredLanguage(),
      });
      if (epoch !== this.epoch) return; // the person started a new conversation meanwhile
      for (const result of reply.tool_results) {
        // Demo call ids repeat across turns; scope them to this turn.
        const scoped = { ...result, call_id: `${id}:${result.call_id}` };
        dispatch({ type: "tool_started", callId: scoped.call_id, name: result.name, label: result.activity.label });
        dispatch({ type: "tool_finished", result: scoped });
        refreshAfterTool(result);
      }
      dispatch({ type: "turn", id: newId("reply"), speaker: "assistant", text: reply.reply, channel: "text" });
    } catch (error) {
      if (epoch !== this.epoch) return;
      const { title, detail } = describeError(error);
      dispatch({ type: "notice", id: newId("error"), text: detail ? `${title}. ${detail}` : title, tone: "warning" });
    } finally {
      dispatch({ type: "responding", responding: false });
    }
  }

  /** The person tapped Approve or Decline. The model can never do this. */
  async decideApproval(itemId: string, approve: boolean): Promise<void> {
    const item = conversation().items.find((i): i is ApprovalItem => i.kind === "approval" && i.id === itemId);
    if (!item || (item.state !== "pending" && item.state !== "failed")) return;
    dispatch({ type: "approval", id: itemId, state: "submitting" });
    try {
      const outcome =
        item.via === "mock"
          ? { ...(await decideMockApproval(item.request.action_id, approve)), message: null }
          : readActionOutcome(
              approve
                ? await voiceApi.approveAction(item.request.action_id)
                : await voiceApi.rejectAction(item.request.action_id),
            );
      // A run-owned action stays "approved" until the run hands it over: no link yet.
      const waiting = outcome.status === "approved" && item.via === "actions";
      const handoffUrl = approve && !waiting ? (outcome.handoffUrl ?? httpsOnly(item.request.handoff_url)) : null;
      refresh(["approvals", "journeys", "runs"]);
      dispatch({
        type: "approval",
        id: itemId,
        state: approve ? "approved" : "declined",
        outcome: {
          message: outcome.message ?? (approve ? tr("copy.approved_0baa5dc") : tr("copy.declined_nothing_was_done_c83b07f")),
          handoffUrl,
        },
      });
      this.tellModel(
        approve
          ? `The person tapped Approve for ${quoteTitle(item.request.title)}. ADAPT's backend confirmed it` +
              (outcome.status ? ` with status "${outcome.status}"` : "") +
              (item.request.simulation_label
                ? ` (${item.request.simulation_label}: a demonstration, nothing real was booked or submitted)`
                : "") +
              (handoffUrl ? ". The official page is ready for them to open from the card on screen" : "") +
              ". Describe exactly this outcome and nothing more."
          : `The person tapped Decline for ${quoteTitle(item.request.title)}. Nothing was done.`,
      );
    } catch (error) {
      if (await this.reconcileDecision(item, error)) return;
      dispatch({ type: "approval", id: itemId, state: "failed" });
      const { title } = describeError(error);
      dispatch({ type: "notice", id: newId("approval"), text: `${title}. Nothing was done.`, tone: "warning" });
      this.tellModel(`Recording the person's decision on ${quoteTitle(item.request.title)} failed. Nothing was done.`);
    }
  }

  /** The action was already decided elsewhere (Journey page, another device): show and
   * speak its real state instead of an error. True when handled. */
  private async reconcileDecision(item: ApprovalItem, error: unknown): Promise<boolean> {
    const alreadyDecided =
      error instanceof ApiError &&
      error.status === 409 &&
      (error.code === "approval_not_pending" || error.code === "invalid_action_transition");
    if (!alreadyDecided || item.via !== "actions") return false;
    try {
      const body = await voiceApi.getAction(item.request.action_id);
      const decision = readRecordedDecision(body);
      if (!decision) return false;
      const outcome = readActionOutcome(body);
      const waiting = outcome.status === "approved";
      dispatch({
        type: "approval",
        id: item.id,
        state: decision,
        outcome: {
          message:
            decision === "declined"
              ? tr("copy.this_was_already_declined_nothing_was_done_22435a5")
              : waiting
                ? tr("copy.this_was_already_approved_adapt_will_hand_it_ove_6b4a82f")
                : tr("copy.this_was_already_approved_5afb069"),
          handoffUrl: decision === "approved" && !waiting ? outcome.handoffUrl : null,
        },
      });
      this.tellModel(
        `${quoteTitle(item.request.title)} had already been ${decision} elsewhere in the app` +
          (outcome.status ? ` (status "${outcome.status}")` : "") +
          ". Tell the person that, and nothing more.",
      );
      return true;
    } catch {
      return false;
    }
  }

  async decideConsent(itemId: string, allow: boolean): Promise<void> {
    const item = conversation().items.find((i): i is ConsentItem => i.kind === "consent" && i.id === itemId);
    if (!item || (item.state !== "pending" && item.state !== "failed")) return;
    dispatch({ type: "consent", id: itemId, state: "saving" });
    try {
      const user = await voiceApi.setConsent(item.request.preference, allow ? "granted" : "declined");
      queryClient.setQueryData(queryKeys.me, user);
      dispatch({ type: "consent", id: itemId, state: allow ? "granted" : "declined" });
      const what = item.request.preference === "faith_personalization" ? tr("copy.faith_personalisation_e576637") : tr("copy.community_personalisation_1e07e84");
      this.tellModel(
        allow
          ? `The person turned on ${what} in the app. You may now retry what needed it.`
          : `The person declined ${what}. Continue without it and don't ask again.`,
      );
    } catch {
      dispatch({ type: "consent", id: itemId, state: "failed" });
    }
  }

  // --- connection -----------------------------------------------------------------------------

  private async connect(gen: number, resumed: boolean): Promise<void> {
    dispatch({ type: "connection", state: resumed ? "reconnecting" : "connecting" });
    const hasHistory = conversationHistory(conversation().items, 1).length > 0;
    this.profile = await detectAudioProfile();

    let session: VoiceSessionOut;
    try {
      session = await voiceApi.createSession({
        language: preferredLanguage(),
        audio_profile: this.profile,
        resumed: resumed || hasHistory,
      });
    } catch (error) {
      if (gen === this.generation) this.connectFailed(gen, resumed, apiProblem(error));
      return;
    }
    if (gen !== this.generation) return;
    if (session.mode !== "live" || !session.client_secret || !session.webrtc_url || !session.session_id) {
      this.fallBackToText(problem("voice_unavailable", session.unavailable_reason));
      return;
    }
    const track = this.mic?.getAudioTracks()[0];
    if (!track) {
      this.fallBackToText(problem("mic_missing"));
      return;
    }
    this.session = session;
    this.labels = new Map(session.tools.map((tool) => [tool.name, tool.label]));

    let connection: RealtimeConnection;
    try {
      connection = await RealtimeConnection.connect({
        clientSecret: session.client_secret,
        webrtcUrl: session.webrtc_url,
        microphone: track,
        audioElement: this.audio(),
        timeoutMs: CONNECT_TIMEOUT_MS,
        onEvent: (event) => this.onEvent(gen, event),
        onLost: (reason) => this.onLost(gen, reason),
        onAutoplayBlocked: () => this.askForTapToPlay(),
      });
    } catch (error) {
      if (gen !== this.generation) return;
      const reason = error instanceof ConnectError ? error.reason : "failed";
      this.connectFailed(
        gen,
        resumed,
        reason === "timeout" ? "connect_timeout" : reason === "rate_limited" ? "rate_limited" : "connect_failed",
      );
      return;
    }
    if (gen !== this.generation) return connection.close();

    this.connection = connection;
    this.attempt = 0;
    this.outMeter?.disconnect();
    this.outMeter = null;
    track.enabled = !conversation().muted;
    dispatch({ type: "connection", state: "connected" });
    dispatch({ type: "problem", problem: null });
    this.restore(conversationHistory(conversation().items, 12));
    if (this.pendingReply) {
      this.pendingReply = false;
      this.send({ type: "response.create" });
    }
    if (resumed) dispatch({ type: "notice", id: newId("reconnected"), text: tr("copy.reconnected_carrying_on_where_you_left_off_15a77f3") });
    void this.wakeLock.acquire();
    setMediaSession(true, this.mediaHandlers);
  }

  /** Re-seed a new call with the conversation so far, so context survives reconnects and
   * the switch from typing to talking. */
  private restore(history: Array<{ role: "user" | "assistant"; text: string }>): void {
    for (const turn of history) {
      this.send(
        turn.role === "user"
          ? { type: "conversation.item.create", item: { type: "message", role: "user", content: [{ type: "input_text", text: turn.text }] } }
          : { type: "conversation.item.create", item: { type: "message", role: "assistant", content: [{ type: "output_text", text: turn.text }] } },
      );
    }
  }

  private connectFailed(gen: number, resumed: boolean, code: ProblemCode): void {
    if (resumed && code !== "session_expired") {
      this.scheduleReconnect(gen);
      return;
    }
    this.teardown();
    dispatch({ type: "connection", state: "failed" });
    dispatch({ type: "problem", problem: problem(code) });
  }

  private onLost(gen: number, _reason: string): void {
    if (gen !== this.generation) return;
    this.connection?.close();
    this.connection = null;
    this.toolTurn.reset();
    dispatch({ type: "audio_reset" });
    this.scheduleReconnect(gen);
  }

  private scheduleReconnect(gen: number): void {
    this.clearRetry();
    if (!navigator.onLine) {
      dispatch({ type: "connection", state: "offline" }); // resumed by the `online` listener
      return;
    }
    this.attempt += 1;
    if (this.attempt > MAX_RECONNECT_ATTEMPTS) {
      this.teardown();
      dispatch({ type: "connection", state: "failed" });
      dispatch({ type: "problem", problem: problem("connection_lost") });
      return;
    }
    dispatch({ type: "connection", state: "reconnecting" });
    this.retryTimer = setTimeout(() => {
      if (gen === this.generation) void this.connect(gen, true);
    }, reconnectDelay(this.attempt));
  }

  private clearRetry(): void {
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.retryTimer = null;
  }

  private fallBackToText(p: Problem): void {
    this.generation++;
    this.teardown();
    dispatch({ type: "mode", mode: "text" });
    dispatch({ type: "connection", state: "idle" });
    dispatch({ type: "problem", problem: p });
  }

  // --- realtime events ------------------------------------------------------------------------

  private onEvent(gen: number, event: ServerEvent): void {
    if (gen !== this.generation) return;
    dispatch({ type: "realtime", event });
    switch (event.type) {
      case "response.created":
        this.toolTurn.responseStarted();
        break;
      case "input_audio_buffer.speech_started":
        this.toolTurn.userSpeech();
        break;
      case "response.done": {
        // Tool calls run only from a completed response. An interrupted, cancelled or
        // incomplete one may carry partial arguments the person never confirmed.
        const calls = (event.response.output ?? []).filter(
          (item): item is FunctionCallItem => item.type === "function_call",
        );
        for (const call of calls) {
          if (event.response.status === "completed") {
            void this.runTool(gen, call.call_id, call.name, call.arguments ?? "{}");
          } else {
            this.send({
              type: "conversation.item.create",
              item: {
                type: "function_call_output",
                call_id: call.call_id,
                output: JSON.stringify({
                  status: "not_run",
                  guidance: tr("copy.interrupted_before_it_ran_don_t_assume_it_happen_36ae8f3"),
                }),
              },
            });
          }
        }
        if (this.toolTurn.responseDone()) this.send({ type: "response.create" });
        if (event.response.status === "failed") {
          dispatch({ type: "notice", id: newId("failed"), text: tr("copy.adapt_couldn_t_finish_that_answer_ask_again_880095e"), tone: "warning" });
        }
        break;
      }
      case "error":
        if (event.error.code && IGNORED_ERRORS.has(event.error.code)) break;
        if (/expired/i.test(event.error.message)) this.onLost(gen, "expired");
        else if (import.meta.env.DEV) console.warn("[voice] realtime provider error");
        break;
      default:
        break;
    }
  }

  private async runTool(gen: number, callId: string, name: string, args: string): Promise<void> {
    if (!this.toolTurn.begin(callId)) return;
    const label = this.labels.get(name) ?? tr("copy.working_on_it_9f56551");
    dispatch({ type: "tool_started", callId, name, label });
    let result: VoiceToolCallResult;
    try {
      result = await voiceApi.runToolCall({
        session_id: this.session?.session_id ?? "",
        call_id: callId,
        name,
        arguments: args,
      });
    } catch (error) {
      result = failedToolResult(callId, name, label, error);
    }
    if (gen !== this.generation) {
      // The call ended meanwhile: settle the row (and show any approval card) but don't
      // talk to a model that is gone.
      if (conversation().items.some((item) => item.id === `tool:${callId}`)) dispatch({ type: "tool_finished", result });
      refreshAfterTool(result);
      return;
    }
    dispatch({ type: "tool_finished", result });
    refreshAfterTool(result);
    this.send({
      type: "conversation.item.create",
      item: { type: "function_call_output", call_id: callId, output: JSON.stringify(result.output) },
    });
    if (this.toolTurn.finish(callId)) this.send({ type: "response.create" });
  }

  private send(event: ClientEvent): void {
    this.connection?.send(event);
  }

  /** App-side facts for the model (decisions made in the UI), as a system message. */
  private tellModel(text: string): void {
    if (!this.connection?.isOpen) return;
    this.send({ type: "conversation.item.create", item: { type: "message", role: "system", content: [{ type: "input_text", text }] } });
    if (!conversation().responding) this.send({ type: "response.create" });
  }

  // --- devices --------------------------------------------------------------------------------

  private primeAudio(): void {
    try {
      this.context ??= new AudioContext();
      void this.context.resume();
    } catch {
      this.context = null; // level meters are decorative
    }
    // Starting playback inside the tap unlocks the element for the reply audio later
    // (iOS and some Android browsers otherwise keep it silent).
    const element = this.audio();
    if (!element.srcObject) {
      try {
        element.srcObject = new MediaStream();
        void element.play().catch(() => undefined);
      } catch {
        /* nothing to unlock on this platform */
      }
    }
  }

  private askForTapToPlay(): void {
    dispatch({ type: "notice", id: newId("sound"), text: tr("copy.tap_anywhere_to_hear_adapt_e84c4ef") });
    document.addEventListener("pointerdown", () => void this.audioElement?.play().catch(() => undefined), { once: true });
  }

  private audio(): HTMLAudioElement {
    if (!this.audioElement) {
      this.audioElement = new Audio();
      this.audioElement.autoplay = true;
    }
    return this.audioElement;
  }

  private useMicrophone(gen: number, stream: MediaStream): void {
    const previous = this.mic;
    this.mic = stream;
    const track = stream.getAudioTracks()[0];
    if (track) {
      track.enabled = !conversation().muted;
      track.onended = () => void this.recoverMicrophone(gen);
    }
    this.micMeter?.disconnect();
    this.micMeter = null;
    if (this.context) {
      try {
        this.micMeter = new LevelMeter(this.context, stream);
      } catch {
        /* decorative */
      }
    }
    if (previous && previous !== stream) stopStream(previous);
  }

  /** The microphone went away (unplugged headset, OS took it, screen locked on iOS). */
  private async recoverMicrophone(gen: number): Promise<void> {
    if (gen !== this.generation || this.recovering) return;
    this.recovering = true;
    try {
      const stream = await acquireMicrophone();
      if (gen !== this.generation) return stopStream(stream);
      const track = stream.getAudioTracks()[0];
      if (track) await this.connection?.replaceMicrophone(track);
      this.useMicrophone(gen, stream);
    } catch (error) {
      if (gen !== this.generation) return;
      this.endVoice();
      dispatch({ type: "problem", problem: problem(error instanceof MicrophoneError ? error.code : "mic_busy") });
    } finally {
      this.recovering = false;
    }
  }

  private releaseMedia(): void {
    stopStream(this.mic);
    this.mic = null;
    this.micMeter?.disconnect();
    this.micMeter = null;
    this.outMeter?.disconnect();
    this.outMeter = null;
    if (this.audioElement) this.audioElement.srcObject = null;
  }

  private readonly mediaHandlers = {
    mute: () => this.toggleMute(),
    end: () => this.endVoice(),
  };

  private attach(): void {
    if (this.attached || typeof window === "undefined") return;
    this.attached = true;

    window.addEventListener("online", () => {
      if (conversation().connection === "offline" && this.mic) {
        this.attempt = 0;
        this.scheduleReconnect(this.generation);
      }
    });

    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState !== "visible" || !this.mic) return;
      void this.wakeLock.refresh();
      const gen = this.generation;
      if (this.connection && !this.connection.healthy) this.onLost(gen, "resumed_unhealthy");
      if (this.mic.getAudioTracks().every((track) => track.readyState === "ended")) void this.recoverMicrophone(gen);
    });

    navigator.mediaDevices?.addEventListener?.("devicechange", () => {
      if (!this.connection) return;
      void detectAudioProfile().then((profile) => {
        if (profile === this.profile) return;
        this.profile = profile;
        this.send({ type: "session.update", session: { type: "realtime", audio: { input: { noise_reduction: { type: profile } } } } });
      });
    });
  }
}

export const voice = new VoiceController();
