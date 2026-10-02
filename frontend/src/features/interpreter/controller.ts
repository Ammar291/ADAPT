import type { InterpreterApi } from "./api";
import { captureMicrophone, InterpreterAudioError, Meter, recordingMime } from "./audio";
import { WebRTCTranslationConnection, type ConnectionCallbacks, type TranslationConnection, type TranslationEvent } from "./connection";
import type { InterpreterEvent, InterpreterEventName, Pair, Session, Snapshot, Speaker } from "./types";

const speakers: Speaker[] = ["a", "b"];
export function initialSnapshot(): Snapshot {
  return { state: "idle", active: "a", muted: false, paused: false, mode: null,
    transcripts: { a: { original: "", translation: "" }, b: { original: "", translation: "" } },
    transports: { a: "webrtc", b: "webrtc" }, error: null, notice: null,
    playbackBlocked: false, recording: false, replayable: { a: false, b: false }, level: 0 };
}
export interface StartOptions { demo?: boolean; headphones?: boolean; devices?: [string, string]; recorded?: boolean }
export interface ControllerDependencies {
  capture: typeof captureMicrophone;
  connection: (callbacks: ConnectionCallbacks) => TranslationConnection;
  audio: () => HTMLAudioElement;
  context: () => AudioContext | null;
}
const defaults: ControllerDependencies = {
  capture: captureMicrophone,
  connection: (cb) => new WebRTCTranslationConnection(cb),
  audio: () => { const audio = new Audio(); audio.autoplay = true; audio.setAttribute("playsinline", ""); return audio; },
  context: () => typeof AudioContext === "undefined" ? null : new AudioContext(),
};

/** Owns only interpretation resources. No imports from ADAPT's assistant/voice state. */
export class InterpreterController {
  private snapshot = initialSnapshot();
  private listeners = new Set<() => void>();
  private notification: ReturnType<typeof setTimeout> | undefined;
  private epoch = 0;
  private abort: AbortController | null = null;
  private session: Session | null = null;
  private connections = new Map<Speaker, TranslationConnection>();
  private roots: MediaStream[] = [];
  private inputs = new Map<Speaker, MediaStream>();
  private outputs = new Map<Speaker, HTMLAudioElement>();
  private meters = new Map<Speaker, Meter>();
  private micMeters = new Map<Speaker, Meter>();
  private context: AudioContext | null = null;
  private interval: ReturnType<typeof setInterval> | undefined;
  private settle = new Map<Speaker, ReturnType<typeof setTimeout>>();
  private retryWait: ReturnType<typeof setTimeout> | undefined;
  private expiry: ReturnType<typeof setTimeout> | undefined;
  private demoTimer: ReturnType<typeof setTimeout> | undefined;
  private recordingLimit: ReturnType<typeof setTimeout> | undefined;
  private recorder: MediaRecorder | null = null;
  private remoteRecorders = new Map<Speaker, MediaRecorder>();
  private replayUrls = new Map<Speaker, string>();
  private seen = new Set<string>();
  private lastSound = 0;
  private playing = false;
  private reconnecting = false;
  private pending = false;
  private detectedSpeakers = new Set<Speaker>();
  private pendingSpeakers = new Set<Speaker>();
  private playbackNodes = new Map<Speaker, { source: MediaStreamAudioSourceNode; delay: DelayNode; destination: MediaStreamAudioDestinationNode }>();
  private options: StartOptions = {};
  private deps: ControllerDependencies;
  constructor(private api: InterpreterApi, deps: Partial<ControllerDependencies> = {}, private onEvent?: (event: InterpreterEvent) => void) { this.deps = { ...defaults, ...deps }; }
  getSnapshot = (): Snapshot => this.snapshot;
  subscribe = (fn: () => void): (() => void) => { this.listeners.add(fn); return () => this.listeners.delete(fn); };
  private update(patch: Partial<Snapshot>, coalesce = false): void {
    this.snapshot = { ...this.snapshot, ...patch };
    if (coalesce) {
      this.notification ??= setTimeout(() => { this.notification = undefined; this.listeners.forEach((fn) => fn()); }, 80);
    } else {
      clearTimeout(this.notification); this.notification = undefined;
      this.listeners.forEach((fn) => fn());
    }
  }
  private emit(name: InterpreterEventName, speaker?: Speaker, code?: string): void {
    const event: InterpreterEvent = { name, speaker, code, state: this.snapshot.state, timestamp: Date.now(), demo: this.snapshot.mode === "demo" };
    this.onEvent?.(event);
    // State/event metadata only. No transcripts, recordings, or credentials in analytics.
    if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent(name, { detail: event }));
  }
  async start(pair: Pair, options: StartOptions = {}): Promise<void> {
    if (["connecting", "reconnecting"].includes(this.snapshot.state)) return;
    this.end(false); this.options = options;
    const epoch = this.epoch; this.abort = new AbortController();
    this.update({ ...initialSnapshot(), state: "connecting" });
    try {
      // Demo preflight prevents mic permissions when server credentials are unavailable.
      const cap = await this.api.capabilities();
      if (epoch !== this.epoch) return;
      const demo = options.demo || cap.mode === "demo";
      if (cap.mode === "unavailable") throw new Error("The interpreter is unavailable. Configure server credentials or choose the demo.");
      if (!demo) {
        if (options.devices && options.devices[0] === options.devices[1]) throw new Error("Choose two different microphone devices to keep speakers separate.");
        const first = await this.deps.capture(options.devices?.[0]);
        if (epoch !== this.epoch) { first.getTracks().forEach((t) => t.stop()); return; }
        this.roots.push(first);
        let second = first;
        if (options.devices) {
          second = await this.deps.capture(options.devices[1]);
          if (epoch !== this.epoch) { second.getTracks().forEach((t) => t.stop()); return; }
          this.roots.push(second);
          if (first.getAudioTracks()[0]?.getSettings().deviceId === second.getAudioTracks()[0]?.getSettings().deviceId) throw new Error("Both inputs resolved to the same microphone. Choose separate devices.");
        }
        for (const [i, speaker] of speakers.entries()) {
          const original = (i === 0 ? first : second).getAudioTracks()[0];
          if (!original) throw new InterpreterAudioError("mic_unavailable", "No microphone audio track is available.");
          const track = original.clone(); track.enabled = false;
          track.onended = () => this.fail(new InterpreterAudioError("mic_ended", "The microphone disconnected. Reconnect it and start again."));
          this.inputs.set(speaker, new MediaStream([track]));
        }
        for (const root of this.roots) for (const track of root.getTracks()) track.onended = () => this.fail(new InterpreterAudioError("mic_ended", "Microphone access ended. Start again when the app is visible."));
        this.context = this.deps.context();
        if (!this.context && !options.headphones) throw new Error("Audio monitoring is unavailable. Use headphones and enable headphone mode to prevent feedback.");
        await this.context?.resume();
        if (epoch !== this.epoch) return;
        for (const speaker of speakers) {
          const output = this.deps.audio(); this.outputs.set(speaker, output);
          // Prime media playback inside this session; rejected play calls are surfaced later.
          void output.play().catch(() => undefined);
          if (this.context) this.micMeters.set(speaker, new Meter(this.context, this.inputs.get(speaker)!));
        }
      }
      const session = await this.api.create({ ...pair, recorded: !!options.recorded }, this.abort.signal);
      if (epoch !== this.epoch) { void this.api.end(session.session_id).catch(() => undefined); return; }
      this.session = session;
      this.update({ mode: session.mode, transports: Object.fromEntries(session.streams.map((s) => [s.speaker, options.recorded && s.transport !== "demo" ? "recorded" : s.transport])) as Snapshot["transports"] });
      await this.connectStreams(session, epoch);
      if (epoch !== this.epoch) return;
      this.update({ state: "listening", notice: session.mode === "demo" ? "Demo: scripted samples. Your microphone is off." : null });
      this.gate(); this.emit("interpreter_started");
      this.interval = setInterval(() => this.monitor(), 50);
      // A 0 or missing stream expiry is unknown, not expired: fall back to the session's.
      this.scheduleExpiry(Math.min(session.expires_at, ...session.streams.map((s) => s.session_expires_at || session.expires_at)), epoch);
    } catch (error) { if (epoch === this.epoch) this.fail(error); }
  }
  private scheduleExpiry(expires: number, epoch: number): void {
    clearTimeout(this.expiry);
    this.expiry = setTimeout(() => {
      if (epoch !== this.epoch || !this.session) return;
      if (this.session.expires_at > Date.now() / 1000 + 5) void this.reconnect();
      else this.fail(new Error("The interpreter session expired. Start a new conversation."));
    }, Math.max(0, expires * 1000 - Date.now() - 1000));
  }
  private async connectStreams(session: Session, epoch: number): Promise<void> {
    for (const credential of session.streams) {
      if (credential.transport !== "webrtc" || this.options.recorded) continue;
      const speaker = credential.speaker;
      const connection = this.deps.connection({
        event: (event) => { if (epoch === this.epoch) this.receive(speaker, event); },
        remote: (stream) => { if (epoch === this.epoch) this.remote(speaker, stream); },
        lost: () => { if (epoch === this.epoch) void this.reconnect(); },
      });
      // Register before connecting so End also cancels pending SDP/ICE work.
      this.connections.set(speaker, connection);
      await connection.connect(credential, this.inputs.get(speaker)!.getAudioTracks()[0]!, this.abort!.signal);
      if (epoch !== this.epoch) { connection.close(); return; }
      if (credential.session_expires_at) this.scheduleExpiry(Math.min(session.expires_at, credential.session_expires_at), epoch);
    }
  }
  private remote(speaker: Speaker, stream: MediaStream): void {
    const audio = this.outputs.get(speaker)!;
    if (this.context) {
      this.meters.get(speaker)?.close(); this.meters.set(speaker, new Meter(this.context, stream));
      // Analyse raw remote audio before it is audible. A small playback delay lets
      // the speakerphone gate close before translated speech reaches the speakers.
      // This graph has no connection to either participant's microphone sender.
      const source = this.context.createMediaStreamSource(stream);
      const delay = this.context.createDelay(1); delay.delayTime.value = this.options.headphones ? 0 : 0.12;
      const destination = this.context.createMediaStreamDestination();
      source.connect(delay); delay.connect(destination);
      this.playbackNodes.set(speaker, { source, delay, destination });
      audio.srcObject = destination.stream;
    } else audio.srcObject = stream;
    void audio.play().catch(() => this.update({ playbackBlocked: true, notice: "Tap Enable audio to hear translations. Subtitles remain available." }));
  }
  private receive(speaker: Speaker, event: TranslationEvent): void {
    if (event.event_id) {
      if (this.seen.has(event.event_id)) return;
      this.seen.add(event.event_id); if (this.seen.size > 2000) this.seen.delete(this.seen.values().next().value!);
    }
    if (event.type === "session.closed") { void this.reconnect(); return; }
    if (event.type === "error") {
      if (event.error?.code?.includes("expir")) void this.reconnect();
      else this.fail(new Error("The translation service reported an error. Restart or choose recorded translation."));
      return;
    }
    if (!event.delta || !["session.input_transcript.delta", "session.output_transcript.delta"].includes(event.type)) return;
    const field = event.type === "session.input_transcript.delta" ? "original" : "translation";
    const transcript = this.snapshot.transcripts[speaker];
    this.update({ transcripts: { ...this.snapshot.transcripts, [speaker]: { ...transcript, [field]: (transcript[field] + event.delta).slice(-6000) } } }, true);
    if (field === "original") {
      if (!this.detectedSpeakers.has(speaker)) { this.detectedSpeakers.add(speaker); this.emit("speaker_detected", speaker); }
      if (!this.pendingSpeakers.has(speaker)) { this.pendingSpeakers.add(speaker); this.pending = true; if (!this.snapshot.paused && !this.playing) this.update({ state: "translating" }); this.emit("translation_started", speaker); }
    } else {
      if (!this.pendingSpeakers.has(speaker)) { this.pendingSpeakers.add(speaker); this.pending = true; this.emit("translation_started", speaker); }
      this.emit("translation_received", speaker);
      clearTimeout(this.settle.get(speaker));
      // Translation has continuous deltas, no server "translation completed" turns.
      // This is an app-level quiet boundary, not an invented provider event.
      this.settle.set(speaker, setTimeout(() => { if (!this.playing) this.complete(speaker); }, 1400));
    }
  }
  private complete(speaker: Speaker): void {
    clearTimeout(this.settle.get(speaker)); this.settle.delete(speaker);
    if (this.pendingSpeakers.has(speaker)) this.emit("translation_completed", speaker);
    this.pendingSpeakers.delete(speaker); this.detectedSpeakers.delete(speaker);
    this.pending = this.pendingSpeakers.size > 0;
    if (!this.snapshot.paused && !this.reconnecting && this.session) this.update({ state: this.playing ? "speaking" : this.pending ? "translating" : "listening" });
  }
  private gate(): void {
    const blocked = !this.session || this.snapshot.paused || this.snapshot.muted || this.reconnecting || this.pending && this.snapshot.transports[this.snapshot.active] === "recorded" || this.playing && !this.options.headphones;
    for (const speaker of speakers) for (const track of this.inputs.get(speaker)?.getTracks() ?? []) {
      track.enabled = !blocked && speaker === this.snapshot.active;
    }
  }
  private monitor(): void {
    let sounding: Speaker | undefined;
    for (const speaker of speakers) {
      const audio = this.outputs.get(speaker);
      if (audio && !audio.paused && !audio.muted && (this.meters.get(speaker)?.level() ?? 0) > 0.008) sounding = speaker;
    }
    if (sounding) {
      this.lastSound = Date.now();
      if (!this.playing) {
        this.playing = true; this.gate();
        if (!this.snapshot.paused) this.update({ state: "speaking" });
        this.emit("audio_playing", sounding); this.recordRemote(sounding);
      }
    } else if (this.playing && Date.now() - this.lastSound > 700) {
      this.playing = false;
      for (const recorder of this.remoteRecorders.values()) if (recorder.state !== "inactive") recorder.stop();
      this.remoteRecorders.clear();
      for (const speaker of [...this.pendingSpeakers]) this.complete(speaker);
      this.gate();
    }
    const level = this.micMeters.get(this.snapshot.active)?.level() ?? 0;
    if (Math.abs(level - this.snapshot.level) > 0.015 || level === 0 && this.snapshot.level !== 0) this.update({ level });
  }
  private recordRemote(speaker: Speaker): void {
    const stream = this.outputs.get(speaker)?.srcObject as MediaStream | null;
    const mime = recordingMime(); if (!stream || !mime || this.remoteRecorders.has(speaker)) return;
    try {
      const epoch = this.epoch; const chunks: Blob[] = []; let size = 0;
      const recorder = new MediaRecorder(stream, { mimeType: mime });
      recorder.ondataavailable = (e) => { size += e.data.size; if (size <= 4 * 1024 * 1024) chunks.push(e.data); else if (recorder.state !== "inactive") recorder.stop(); };
      recorder.onstop = () => { if (epoch === this.epoch && chunks.length) this.saveReplay(speaker, new Blob(chunks, { type: mime })); };
      this.remoteRecorders.set(speaker, recorder); recorder.start(200);
    } catch { /* Replay is optional when recording remote WebRTC audio is unsupported. */ }
  }
  private saveReplay(speaker: Speaker, blob: Blob): void {
    const old = this.replayUrls.get(speaker); if (old) URL.revokeObjectURL(old);
    this.replayUrls.set(speaker, URL.createObjectURL(blob));
    this.update({ replayable: { ...this.snapshot.replayable, [speaker]: true } });
  }
  selectSpeaker(speaker: Speaker): void {
    if (!this.session || this.snapshot.recording || this.pending && this.snapshot.transports[this.snapshot.active] === "recorded") return;
    // No diarization guesses: on a shared microphone the user identifies the source.
    this.update({ active: speaker }); this.gate();
  }
  mute(): void {
    if (this.snapshot.recording) this.cancelRecording();
    this.update({ muted: !this.snapshot.muted }); this.gate();
  }
  pause(): void {
    if (!this.session) return; this.cancelRecording();
    this.update({ paused: true, state: "paused" }); this.gate();
    for (const output of this.outputs.values()) { output.muted = true; }
  }
  async resume(): Promise<void> {
    if (!this.session || this.reconnecting) return;
    this.replayAudio?.pause(); this.replayAudio = null;
    try { await this.context?.resume(); }
    catch { this.update({ notice: "Tap Enable audio to resume playback." }); }
    this.update({ paused: false, state: "listening" });
    for (const output of this.outputs.values()) output.muted = false;
    this.gate(); await this.enableAudio();
  }
  async enableAudio(): Promise<void> {
    try {
      await this.context?.resume();
      if (this.replayAudio) await this.replayAudio.play();
      else for (const output of this.outputs.values()) if (output.srcObject || output.src && !output.ended) await output.play();
      this.update({ playbackBlocked: false, notice: null });
    } catch { this.update({ playbackBlocked: true, notice: "Audio playback is blocked. Tap Enable audio again or read the subtitles." }); }
  }
  async replay(speaker: Speaker): Promise<void> {
    const url = this.replayUrls.get(speaker); if (!url || !this.session) return;
    // Replay always closes microphone gates, including in headphone mode.
    this.pause();
    const replay = this.deps.audio();
    replay.autoplay = false; replay.src = url;
    this.update({ notice: "Replaying translation. Resume when you are ready to speak." });
    this.replayAudio?.pause(); this.replayAudio = replay;
    replay.onplaying = () => this.emit("audio_playing", speaker);
    try { await replay.play(); } catch { this.update({ playbackBlocked: true }); }
  }
  private replayAudio: HTMLAudioElement | null = null;
  async reconnect(): Promise<void> {
    if (!this.session || this.reconnecting || this.snapshot.mode === "demo") return;
    const epoch = this.epoch; this.reconnecting = true;
    const sessionId = this.session.session_id;
    this.update({ state: "reconnecting", notice: "Connection lost. Getting fresh translation sessions…" }); this.gate(); this.emit("reconnecting");
    this.closeConnections();
    for (let attempt = 0; attempt < 3 && epoch === this.epoch; attempt++) {
      try {
        const session = await this.api.reconnect(sessionId, this.abort!.signal);
        if (epoch !== this.epoch) return;
        this.session = session; this.seen.clear();
        await this.connectStreams(session, epoch);
        if (epoch !== this.epoch) return;
        this.reconnecting = false;
        this.scheduleExpiry(Math.min(session.expires_at, ...session.streams.map((s) => s.session_expires_at || session.expires_at)), epoch);
        this.update({ state: this.snapshot.paused ? "paused" : "listening", notice: null }); this.gate(); return;
      } catch (error) {
        this.closeConnections();
        if (epoch !== this.epoch) return;
        if (attempt === 2) { this.fail(new Error(`Could not reconnect. ${error instanceof Error ? error.message : "Start again or use recorded translation."}`)); return; }
        await new Promise<void>((resolve) => {
          const done = () => { clearTimeout(this.retryWait); this.abort?.signal.removeEventListener("abort", done); resolve(); };
          this.retryWait = setTimeout(done, 500 * 2 ** attempt); this.abort!.signal.addEventListener("abort", done, { once: true });
        });
      }
    }
  }
  private closeConnections(): void {
    for (const timer of this.settle.values()) clearTimeout(timer); this.settle.clear();
    for (const recorder of this.remoteRecorders.values()) { recorder.onstop = null; if (recorder.state !== "inactive") recorder.stop(); } this.remoteRecorders.clear();
    for (const connection of this.connections.values()) connection.close(); this.connections.clear();
    for (const meter of this.meters.values()) meter.close(); this.meters.clear();
    for (const nodes of this.playbackNodes.values()) { nodes.source.disconnect(); nodes.delay.disconnect(); nodes.destination.stream.getTracks().forEach((track) => track.stop()); }
    this.playbackNodes.clear();
    for (const output of this.outputs.values()) { output.onended = null; output.onplaying = null; output.onerror = null; output.pause(); output.srcObject = null; output.removeAttribute("src"); }
    this.playing = false; this.pending = false; this.pendingSpeakers.clear(); this.detectedSpeakers.clear();
  }
  /** Recorded fallback captures a bounded phrase from only the selected input track. */
  async record(): Promise<void> {
    if (this.snapshot.mode === "demo") { this.sample(); return; }
    if (this.snapshot.recording) { this.recorder?.stop(); return; }
    if (!this.session || this.snapshot.paused || this.snapshot.muted || this.playing || this.pending) return;
    const mime = recordingMime();
    if (!mime) { this.update({ notice: "This browser cannot record the fallback. Try current Chrome or Safari." }); return; }
    const speaker = this.snapshot.active; const epoch = this.epoch; const chunks: Blob[] = [];
    const recorder = this.recorder = new MediaRecorder(this.inputs.get(speaker)!, { mimeType: mime });
    recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
    recorder.onerror = () => this.fail(new Error("Microphone recording failed. Try another browser or input."));
    recorder.onstop = () => {
      clearTimeout(this.recordingLimit); this.recorder = null;
      if (epoch !== this.epoch) return;
      this.update({ recording: false, state: "translating" }); this.pending = true; this.pendingSpeakers.add(speaker); this.gate(); this.emit("translation_started", speaker);
      void this.sendRecording(speaker, new Blob(chunks, { type: mime }), epoch);
    };
    this.update({ recording: true, state: "listening" }); this.gate(); recorder.start(); this.emit("speaker_detected", speaker);
    this.recordingLimit = setTimeout(() => { if (recorder.state !== "inactive") recorder.stop(); }, 25_000);
  }
  private cancelRecording(): void {
    clearTimeout(this.recordingLimit);
    if (this.recorder) { this.recorder.onstop = null; if (this.recorder.state !== "inactive") this.recorder.stop(); this.recorder = null; }
    this.update({ recording: false });
  }
  private async sendRecording(speaker: Speaker, blob: Blob, epoch: number): Promise<void> {
    try {
      const result = await this.api.recording(this.session!.session_id, speaker, blob, this.abort!.signal);
      if (epoch !== this.epoch) return;
      this.update({ transcripts: { ...this.snapshot.transcripts, [speaker]: { original: result.original, translation: result.translation } }, notice: result.audio_error ?? (!result.translation ? "No speech was detected. Try a clearer phrase." : null) });
      this.emit("translation_received", speaker);
      if (result.audio_base64) {
        const bytes = Uint8Array.from(atob(result.audio_base64), (c) => c.charCodeAt(0));
        this.saveReplay(speaker, new Blob([bytes], { type: result.audio_mime }));
        const output = this.outputs.get(speaker)!; output.srcObject = null; output.src = this.replayUrls.get(speaker)!;
        output.onplaying = () => { if (epoch === this.epoch && !this.snapshot.paused) { this.update({ state: "speaking" }); this.emit("audio_playing", speaker); } };
        output.onended = () => { if (epoch === this.epoch) { this.complete(speaker); this.gate(); } };
        output.onerror = () => { if (epoch === this.epoch) { this.complete(speaker); this.gate(); this.update({ notice: "Audio failed. The translated text is available." }); } };
        if (!this.snapshot.paused) await output.play().catch(() => this.update({ playbackBlocked: true, notice: "Tap Enable audio to play the recorded translation." }));
      } else { this.complete(speaker); this.gate(); }
    } catch (error) { if (epoch === this.epoch) { this.pendingSpeakers.delete(speaker); this.detectedSpeakers.delete(speaker); this.pending = this.pendingSpeakers.size > 0; this.gate(); this.update({ state: this.snapshot.paused ? "paused" : this.pending ? "translating" : "listening", notice: error instanceof Error ? error.message : "Recorded translation failed." }); this.emit("interpreter_error", speaker, "fallback_failed"); } }
  }
  sample(): void {
    if (this.snapshot.mode !== "demo" || this.snapshot.paused || this.snapshot.muted || this.pending) return;
    const speaker = this.snapshot.active; const stream = this.session!.streams.find((s) => s.speaker === speaker)!;
    const samples: Record<string, string> = { en: "I need help finding this address.", ar: "أحتاج إلى مساعدة في العثور على هذا العنوان.", hi: "मुझे यह पता ढूँढने में मदद चाहिए।" };
    const response: Record<string, string> = { en: "Of course. Let me show you the way.", ar: "بالطبع. دعني أريك الطريق.", hi: "ज़रूर। मैं आपको रास्ता दिखाता हूँ।" };
    const text = speaker === "a" ? samples : response;
    this.pending = true; this.pendingSpeakers.add(speaker); this.update({ state: "translating" }); this.emit("speaker_detected", speaker); this.emit("translation_started", speaker);
    const epoch = this.epoch;
    this.demoTimer = setTimeout(() => {
      if (epoch !== this.epoch) return;
      this.update({ transcripts: { ...this.snapshot.transcripts, [speaker]: { original: text[stream.source] ?? "Sample unavailable for this language.", translation: text[stream.target] ?? "Sample unavailable for this language." } } });
      this.emit("translation_received", speaker); this.complete(speaker);
    }, 650);
  }
  private fail(error: unknown): void {
    const message = error instanceof Error ? error.message : "The interpreter could not start. Try again.";
    const code = error instanceof InterpreterAudioError ? error.code : "interpreter_failed";
    this.end(false); this.update({ state: "error", error: message }); this.emit("interpreter_error", undefined, code);
  }
  end(emit = true): void {
    this.epoch++; this.abort?.abort(); this.abort = null;
    clearInterval(this.interval); for (const timer of this.settle.values()) clearTimeout(timer); this.settle.clear(); clearTimeout(this.expiry); clearTimeout(this.retryWait); clearTimeout(this.demoTimer);
    this.cancelRecording(); this.closeConnections();
    for (const recorder of this.remoteRecorders.values()) { recorder.onstop = null; if (recorder.state !== "inactive") recorder.stop(); } this.remoteRecorders.clear();
    for (const stream of [...this.roots, ...this.inputs.values()]) for (const track of stream.getTracks()) { track.onended = null; track.stop(); }
    this.roots = []; this.inputs.clear();
    for (const meter of this.micMeters.values()) meter.close(); this.micMeters.clear();
    void this.context?.close().catch(() => undefined); this.context = null;
    for (const output of this.outputs.values()) { output.onended = null; output.onplaying = null; output.onerror = null; output.pause(); output.srcObject = null; output.removeAttribute("src"); output.load(); } this.outputs.clear();
    this.replayAudio?.pause(); this.replayAudio = null;
    for (const url of this.replayUrls.values()) URL.revokeObjectURL(url); this.replayUrls.clear();
    if (this.session) void this.api.end(this.session.session_id).catch(() => undefined);
    this.session = null; this.reconnecting = false; this.pending = false; this.seen.clear();
    this.update({ state: this.snapshot.state === "idle" && !emit ? "idle" : "stopped", paused: false, muted: false, recording: false, level: 0, replayable: { a: false, b: false }, playbackBlocked: false });
    if (emit) this.emit("interpreter_stopped");
  }
}
