import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { demoApi, demoCapabilities, type InterpreterApi } from "./api";
import { microphoneProblem, InterpreterAudioError, recordingMime } from "./audio";
import { setUiLocale } from "@/i18n";
import { InterpreterController } from "./controller";
import { InterpreterTranscript } from "./InterpreterPage";
import { direction, pairFromSearch, pairProblem, swapPair } from "./languages";
import { parseTranslationEvent, WebRTCTranslationConnection, type ConnectionCallbacks } from "./connection";
import type { RecordingResult, Session } from "./types";

class Track {
  enabled = true; stopped = false; onended: (() => void) | null = null;
  clone() { return new Track(); }
  stop() { this.stopped = true; }
  getSettings() { return { deviceId: "physical-microphone" }; }
}
class Stream {
  constructor(private tracks: Track[] = [new Track()]) {}
  getTracks() { return this.tracks; } getAudioTracks() { return this.tracks; }
}
function audio() { return { paused: true, muted: false, src: "", srcObject: null, setAttribute: vi.fn(), removeAttribute: vi.fn(), load: vi.fn(), play: vi.fn().mockResolvedValue(undefined), pause: vi.fn() } as unknown as HTMLAudioElement; }
function session(id = "session-1"): Session {
  return { session_id: id, mode: "live", expires_at: Date.now() / 1000 + 3600, streams: [
    { speaker: "a", source: "en", target: "hi", transport: "webrtc", client_secret: "ek-a", credential_expires_at: Date.now() / 1000 + 120, webrtc_url: "https://api.openai.com/v1/realtime/translations/calls" },
    { speaker: "b", source: "hi", target: "en", transport: "webrtc", client_secret: "ek-b", credential_expires_at: Date.now() / 1000 + 120, webrtc_url: "https://api.openai.com/v1/realtime/translations/calls" },
  ] };
}
function harness() {
  const root = new Stream(); const callbacks: ConnectionCallbacks[] = []; const sent: Track[] = []; const closes: ReturnType<typeof vi.fn>[] = [];
  const api: InterpreterApi = { ...demoApi, capabilities: vi.fn(async () => ({ ...demoCapabilities, mode: "live" as const })), create: vi.fn(async () => session()), reconnect: vi.fn(async () => session("renewed")), end: vi.fn(async () => undefined) };
  const capture = vi.fn(async () => root as unknown as MediaStream);
  const events: string[] = []; const outputs: HTMLAudioElement[] = [];
  const controller = new InterpreterController(api, { capture, audio: () => { const output = audio(); outputs.push(output); return output; }, context: () => null, connection: (cb) => {
    callbacks.push(cb); const close = vi.fn(); closes.push(close);
    return { connect: async (_credential, track) => { sent.push(track as unknown as Track); }, close };
  } }, (e) => events.push(e.name));
  return { controller, api, root, capture, sent, callbacks, closes, events, outputs };
}
beforeEach(() => { vi.stubGlobal("MediaStream", Stream); });
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("interpreter languages", () => {
  it("reads deep links and defaults", () => { expect(pairFromSearch("")).toEqual({ source: "en", target: "ar" }); expect(pairFromSearch("source=EN&target=HI")).toEqual({ source: "en", target: "hi" }); });
  it("swaps both directions without mixing speakers", () => { const p = { source: "en", target: "ar" }; expect(swapPair(p)).toEqual({ source: "ar", target: "en" }); expect(direction(p, "b")).toEqual(swapPair(p)); expect(swapPair(swapPair(p))).toEqual(p); });
  it("accepts Hindi realtime and Arabic only with recorded fallback", () => { expect(pairProblem({ source: "en", target: "hi" }, demoCapabilities)).toBeNull(); expect(pairProblem({ source: "en", target: "ar" }, demoCapabilities)).toBeNull(); expect(pairProblem({ source: "en", target: "ar" }, { ...demoCapabilities, fallback_enabled: false })).toContain("input only"); });
  it("rejects unknown and identical languages", () => { expect(pairProblem({ source: "en", target: "xx" }, demoCapabilities)).toContain("does not offer"); expect(pairProblem({ source: "en", target: "en" }, demoCapabilities)).toContain("different"); });
});

describe("interpreter lifecycle", () => {
  it("asks for no microphone before start and gates selected streams on pause, mute, and end", async () => {
    const h = harness(); expect(h.capture).not.toHaveBeenCalled();
    await h.controller.start({ source: "en", target: "hi" }, { headphones: true });
    expect(h.sent).toHaveLength(2); expect(h.sent[0]!.enabled).toBe(true); expect(h.sent[1]!.enabled).toBe(false);
    h.controller.selectSpeaker("b"); expect(h.sent.map((t) => t.enabled)).toEqual([false, true]);
    h.controller.mute(); expect(h.sent.every((t) => !t.enabled)).toBe(true);
    h.controller.mute(); h.controller.pause(); expect(h.sent.every((t) => !t.enabled)).toBe(true);
    await h.controller.resume(); expect(h.sent.map((t) => t.enabled)).toEqual([false, true]);
    h.controller.end(); expect([...h.sent, ...h.root.getTracks()].every((t) => t.stopped)).toBe(true); expect(h.api.end).toHaveBeenCalledWith("session-1"); expect(h.events).toContain("interpreter_started"); expect(h.events.at(-1)).toBe("interpreter_stopped");
  });
  it("keeps continuous source/translation deltas and speaker identities separate, deduplicating event IDs", async () => {
    const h = harness(); await h.controller.start({ source: "en", target: "hi" }, { headphones: true });
    h.callbacks[0]!.event({ type: "session.input_transcript.delta", event_id: "i1", delta: "Find" });
    h.callbacks[0]!.event({ type: "session.input_transcript.delta", event_id: "i2", delta: " this address." });
    h.callbacks[0]!.event({ type: "session.output_transcript.delta", event_id: "o1", delta: "यह पता" });
    h.callbacks[0]!.event({ type: "session.output_transcript.delta", event_id: "o1", delta: "यह पता" });
    h.callbacks[1]!.event({ type: "session.input_transcript.delta", event_id: "i3", delta: "नमस्ते" });
    const t = h.controller.getSnapshot().transcripts;
    expect(t.a).toEqual({ original: "Find this address.", translation: "यह पता" }); expect(t.b.original).toBe("नमस्ते"); expect(t.b.translation).toBe(""); expect(h.events).toContain("translation_started"); h.controller.end();
  });
  it("gets fresh credentials on reconnect while preserving pause and transcripts", async () => {
    const h = harness(); await h.controller.start({ source: "en", target: "hi" }, { headphones: true });
    h.callbacks[0]!.event({ type: "session.input_transcript.delta", delta: "Hello" }); h.controller.pause();
    await h.controller.reconnect(); expect(h.api.reconnect).toHaveBeenCalledWith("session-1", expect.any(AbortSignal)); expect(h.controller.getSnapshot().state).toBe("paused"); expect(h.sent.every((t) => !t.enabled)).toBe(true); expect(h.controller.getSnapshot().transcripts.a.original).toBe("Hello"); expect(h.closes[0]).toHaveBeenCalled(); h.controller.end();
  });
  it("treats a provider stream expiry of 0 as unknown instead of reconnecting at once", async () => {
    vi.useFakeTimers(); const h = harness();
    const unstarted = (id: string) => { const s = session(id); return { ...s, streams: s.streams.map((stream) => ({ ...stream, session_expires_at: 0 })) }; };
    vi.mocked(h.api.create).mockResolvedValue(unstarted("session-1")); vi.mocked(h.api.reconnect).mockResolvedValue(unstarted("renewed"));
    await h.controller.start({ source: "en", target: "hi" }, { headphones: true }); await vi.advanceTimersByTimeAsync(10_000);
    expect(h.api.reconnect).not.toHaveBeenCalled(); expect(h.controller.getSnapshot().state).toBe("listening");
    await h.controller.reconnect(); await vi.advanceTimersByTimeAsync(10_000);
    expect(h.api.reconnect).toHaveBeenCalledTimes(1); h.controller.end();
  });
  it("stops and releases the microphone after bounded reconnect failure", async () => {
    vi.useFakeTimers(); const h = harness(); await h.controller.start({ source: "en", target: "hi" }, { headphones: true });
    vi.mocked(h.api.reconnect).mockRejectedValue(new Error("Network unavailable"));
    const retry = h.controller.reconnect(); await vi.advanceTimersByTimeAsync(2500); await retry;
    expect(h.api.reconnect).toHaveBeenCalledTimes(3); expect(h.controller.getSnapshot().state).toBe("error"); expect(h.root.getTracks()[0]!.stopped).toBe(true); expect(h.events).toContain("reconnecting"); h.controller.end();
  });
  it("cancels a late microphone permission grant after End", async () => {
    const h = harness(); let grant: (s: MediaStream) => void = () => undefined;
    h.capture.mockImplementation(() => new Promise((resolve) => { grant = resolve; }));
    const start = h.controller.start({ source: "en", target: "hi" }, { headphones: true });
    await Promise.resolve(); h.controller.end(); grant(h.root as unknown as MediaStream); await start;
    expect(h.root.getTracks()[0]!.stopped).toBe(true); expect(h.api.create).not.toHaveBeenCalled(); expect(h.controller.getSnapshot().state).toBe("stopped");
  });
  it("surfaces microphone failures without minting provider credentials", async () => {
    const h = harness(); h.capture.mockRejectedValue(new InterpreterAudioError("mic_denied", "Permission denied"));
    await h.controller.start({ source: "en", target: "hi" }, { headphones: true }); expect(h.api.create).not.toHaveBeenCalled(); expect(h.controller.getSnapshot().error).toBe("Permission denied"); expect(h.controller.getSnapshot().state).toBe("error"); h.controller.end();
  });
  it("demo mode never captures audio or reports audio playback", async () => {
    vi.useFakeTimers(); const capture = vi.fn(); const events: string[] = [];
    const c = new InterpreterController(demoApi, { capture }, (e) => events.push(e.name));
    await c.start({ source: "en", target: "ar" }, { demo: true }); c.sample(); await vi.advanceTimersByTimeAsync(700);
    expect(capture).not.toHaveBeenCalled(); expect(c.getSnapshot().transcripts.a.translation).toContain("العنوان"); expect(events).not.toContain("audio_playing"); expect(events).toContain("translation_completed"); c.end();
  });
  it("rejects identical microphone device selections", async () => { const h = harness(); await h.controller.start({ source: "en", target: "hi" }, { devices: ["mic", "mic"] }); expect(h.capture).not.toHaveBeenCalled(); expect(h.controller.getSnapshot().error).toContain("different microphone"); });
  it("completes each participant independently and cancels old quiet timers on reconnect", async () => {
    vi.useFakeTimers(); const h = harness(); await h.controller.start({ source: "en", target: "hi" }, { headphones: true });
    h.callbacks[0]!.event({ type: "session.output_transcript.delta", delta: "Translation A" });
    await vi.advanceTimersByTimeAsync(500);
    h.callbacks[1]!.event({ type: "session.output_transcript.delta", delta: "Translation B" });
    await vi.advanceTimersByTimeAsync(950);
    expect(h.events.filter((e) => e === "translation_completed")).toHaveLength(1);
    expect(h.controller.getSnapshot().state).toBe("translating");
    await h.controller.reconnect(); await vi.advanceTimersByTimeAsync(1500);
    expect(h.events.filter((e) => e === "translation_completed")).toHaveLength(1);
    expect(h.controller.getSnapshot().state).toBe("listening"); h.controller.end();
  });
  it("retries blocked replay audio from the Enable audio gesture", async () => {
    const h = harness(); await h.controller.start({ source: "en", target: "hi" }, { headphones: true });
    class Recorder {
      static isTypeSupported() { return true; }
      state = "recording"; ondataavailable: ((e: { data: Blob }) => void) | null = null; onstop: (() => void) | null = null;
      start() {} stop() { this.state = "inactive"; this.ondataavailable?.({ data: new Blob(["audio"]) }); this.onstop?.(); }
    }
    vi.stubGlobal("MediaRecorder", Recorder);
    h.api.recording = vi.fn(async () => ({ speaker: "a" as const, original: "Help", translation: "Translated", audio_base64: "YXVkaW8=", audio_mime: "audio/mpeg" }));
    // Use the public recorded mode rather than injecting private replay data.
    h.controller.end(); vi.mocked(h.api.create).mockResolvedValue({ ...session(), streams: session().streams.map((s) => ({ ...s, transport: "recorded" })) });
    await h.controller.start({ source: "en", target: "hi" }, { headphones: true, recorded: true });
    await h.controller.record(); await h.controller.record(); await vi.waitFor(() => expect(h.controller.getSnapshot().replayable.a).toBe(true));
    const replayPromise = h.controller.replay("a"); const replay = h.outputs.at(-1)!;
    await replayPromise;
    vi.mocked(replay.play).mockRejectedValueOnce(new Error("gesture needed"));
    await h.controller.enableAudio(); expect(h.controller.getSnapshot().playbackBlocked).toBe(true);
    await h.controller.enableAudio(); expect(h.controller.getSnapshot().playbackBlocked).toBe(false);
    expect(h.sent.every((t) => !t.enabled || t.stopped)).toBe(true); expect(h.controller.getSnapshot().paused).toBe(true); h.controller.end();
  });
  it("retains fallback text when playback fails, then allows another recording", async () => {
    const h = harness(); let recording: { stop(): void };
    class Recorder {
      static isTypeSupported() { return true; }
      state = "recording"; ondataavailable: ((e: { data: Blob }) => void) | null = null; onstop: (() => void) | null = null;
      constructor() { recording = this; } start() {} stop() { this.state = "inactive"; this.ondataavailable?.({ data: new Blob(["audio"]) }); this.onstop?.(); }
    }
    vi.stubGlobal("MediaRecorder", Recorder);
    vi.mocked(h.api.create).mockResolvedValue({ ...session(), streams: session().streams.map((s) => ({ ...s, transport: "recorded" })) });
    h.api.recording = vi.fn(async () => ({ speaker: "a" as const, original: "Help", translation: "Translated", audio_base64: "YXVkaW8=", audio_mime: "audio/mpeg" }));
    await h.controller.start({ source: "en", target: "hi" }, { headphones: true, recorded: true });
    await h.controller.record(); recording!.stop(); await vi.waitFor(() => expect(h.controller.getSnapshot().replayable.a).toBe(true));
    h.outputs[0]!.onerror?.(new Event("error"));
    expect(h.controller.getSnapshot().transcripts.a).toEqual({ original: "Help", translation: "Translated" });
    expect(h.controller.getSnapshot().state).toBe("listening");
    await h.controller.record(); expect(h.controller.getSnapshot().recording).toBe(true); h.controller.end();
  });
  it("keeps paused microphones closed when a fallback request fails", async () => {
    const h = harness(); let reject: (error: Error) => void = () => undefined;
    class Recorder {
      static isTypeSupported() { return true; } state = "recording"; onstop: (() => void) | null = null;
      start() {} stop() { this.state = "inactive"; this.onstop?.(); }
    }
    vi.stubGlobal("MediaRecorder", Recorder);
    vi.mocked(h.api.create).mockResolvedValue({ ...session(), streams: session().streams.map((s) => ({ ...s, transport: "recorded" })) });
    h.api.recording = vi.fn(() => new Promise<RecordingResult>((_resolve, rejectRequest) => { reject = rejectRequest; }));
    await h.controller.start({ source: "en", target: "hi" }, { headphones: true, recorded: true });
    await h.controller.record(); await h.controller.record(); h.controller.pause(); reject(new Error("Network lost"));
    await vi.waitFor(() => expect(h.controller.getSnapshot().notice).toBe("Network lost"));
    expect(h.controller.getSnapshot().state).toBe("paused"); await h.controller.resume();
    await h.controller.record(); expect(h.controller.getSnapshot().recording).toBe(true); h.controller.end();
  });
});

describe("permissions and rendering", () => {
  it("keeps recording formats valid after the UI switches to Arabic", async () => {
    vi.stubGlobal("MediaRecorder", { isTypeSupported: (mime: string) => mime === "audio/webm;codecs=opus" });
    await setUiLocale("ar", false);
    try { expect(recordingMime()).toBe("audio/webm;codecs=opus"); }
    finally { await setUiLocale("en", false); }
  });
  it.each([["NotAllowedError", "mic_denied"], ["SecurityError", "mic_denied"], ["NotFoundError", "mic_unavailable"], ["OverconstrainedError", "mic_unavailable"], ["NotReadableError", "mic_busy"]])("explains %s", (name, code) => expect(microphoneProblem(new DOMException("", name)).code).toBe(code));
  it("renders Original and Translation independently with Arabic RTL and escaped content", () => {
    const html = renderToStaticMarkup(createElement(InterpreterTranscript, { transcript: { original: "<script>help</script>", translation: "أحتاج إلى مساعدة" }, source: demoCapabilities.languages[0]!, target: demoCapabilities.languages[1]!, subtitles: true }));
    expect(html).toContain("Original"); expect(html).toContain("Translation"); expect(html).toContain('lang="ar" dir="rtl"'); expect(html).toContain("&lt;script&gt;"); expect(html).not.toContain("<script>");
  });
  it("subtitle toggle hides text without erasing it", () => { const html = renderToStaticMarkup(createElement(InterpreterTranscript, { transcript: { original: "secret", translation: "سري" }, source: demoCapabilities.languages[0]!, target: demoCapabilities.languages[1]!, subtitles: false })); expect(html).toContain("Subtitles are hidden"); expect(html).not.toContain("secret"); });
});

describe("dedicated translation transport", () => {
  it("refuses a primary API key before contacting the translation endpoint", async () => {
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
    const connection = new WebRTCTranslationConnection({ event: vi.fn(), remote: vi.fn(), lost: vi.fn() });
    await expect(connection.connect({ ...session().streams[0]!, client_secret: "sk-test-invalid-browser-credential" }, new Track() as unknown as MediaStreamTrack, new AbortController().signal)).rejects.toThrow("invalid");
    expect(fetch).not.toHaveBeenCalled();
  });
  it("parses translation deltas and ignores malformed packets", () => { expect(parseTranslationEvent('{"type":"session.output_transcript.delta","delta":"hello"}')?.delta).toBe("hello"); expect(parseTranslationEvent("bad json")).toBeNull(); expect(parseTranslationEvent('{"type":"session.input_transcript.delta","delta":1}')).toBeNull(); });
  it("uses the translation endpoint and handles session.created before SDP resolves", async () => {
    const channel = { onmessage: null as null | ((event: { data: string }) => void), onclose: null, close: vi.fn() };
    const pc = { createDataChannel: () => channel, addTrack: vi.fn(), createOffer: async () => ({ type: "offer", sdp: "offer" }), setLocalDescription: vi.fn(async () => undefined), localDescription: { sdp: "offer" }, setRemoteDescription: async () => { channel.onmessage?.({ data: '{"type":"session.created"}' }); }, close: vi.fn() };
    vi.stubGlobal("RTCPeerConnection", class { constructor() { return pc; } });
    const fetch = vi.fn(async () => new Response("answer")); vi.stubGlobal("fetch", fetch);
    const connection = new WebRTCTranslationConnection({ event: vi.fn(), remote: vi.fn(), lost: vi.fn() });
    await connection.connect(session().streams[0]!, new Track() as unknown as MediaStreamTrack, new AbortController().signal);
    expect(fetch).toHaveBeenCalledWith("https://api.openai.com/v1/realtime/translations/calls", expect.objectContaining({ headers: { Authorization: "Bearer ek-a", "Content-Type": "application/sdp" }, credentials: "omit" }));
    connection.close(); expect(pc.close).toHaveBeenCalled();
  });
  it("refuses credentials for an untrusted endpoint", async () => { const connection = new WebRTCTranslationConnection({ event: vi.fn(), remote: vi.fn(), lost: vi.fn() }); await expect(connection.connect({ ...session().streams[0]!, webrtc_url: "https://example.org/steal" }, new Track() as unknown as MediaStreamTrack, new AbortController().signal)).rejects.toThrow("invalid"); });
});
