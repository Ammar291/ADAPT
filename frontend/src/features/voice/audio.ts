import { tr } from "@/i18n";
/**
 * Browser audio plumbing: microphone access, level meters for the orb, screen wake lock
 * and lock-screen metadata. Every API is feature-detected; nothing here is required for
 * the conversation itself to work.
 */
import type { ProblemCode } from "./conversation";
import { audioProfileFor } from "./orchestration";
import type { AudioProfile } from "./types";

export class MicrophoneError extends Error {
  constructor(readonly code: ProblemCode) {
    super(code);
    this.name = "MicrophoneError";
  }
}

export function voiceSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof RTCPeerConnection !== "undefined" &&
    Boolean(navigator.mediaDevices?.getUserMedia)
  );
}

const MIC_CONSTRAINTS: MediaStreamConstraints = {
  audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
};

/** Ask for the microphone and translate each failure into something the UI can explain. */
export async function acquireMicrophone(): Promise<MediaStream> {
  if (!window.isSecureContext) throw new MicrophoneError("insecure_context");
  if (!voiceSupported()) throw new MicrophoneError("unsupported");
  try {
    return await navigator.mediaDevices.getUserMedia(MIC_CONSTRAINTS);
  } catch (error) {
    const name = error instanceof DOMException ? error.name : "";
    if (name === "NotAllowedError" || name === "SecurityError") throw new MicrophoneError("mic_denied");
    if (name === "NotFoundError" || name === "OverconstrainedError") throw new MicrophoneError("mic_missing");
    throw new MicrophoneError("mic_busy");
  }
}

export async function detectAudioProfile(): Promise<AudioProfile> {
  const coarse = typeof matchMedia === "function" && matchMedia("(pointer: coarse)").matches;
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    return audioProfileFor(
      devices.filter((d) => d.kind === "audioinput" || d.kind === "audiooutput").map((d) => d.label),
      coarse,
    );
  } catch {
    return coarse ? "near_field" : "far_field";
  }
}

/** Smoothed 0–1 loudness of a media stream, read on animation frames by the orb. */
export class LevelMeter {
  private readonly analyser: AnalyserNode;
  private readonly source: MediaStreamAudioSourceNode;
  private readonly buffer: Uint8Array<ArrayBuffer>;
  private smoothed = 0;

  constructor(context: AudioContext, stream: MediaStream) {
    this.source = context.createMediaStreamSource(stream);
    this.analyser = context.createAnalyser();
    this.analyser.fftSize = 512;
    this.buffer = new Uint8Array(new ArrayBuffer(this.analyser.fftSize));
    this.source.connect(this.analyser);
  }

  level(): number {
    this.analyser.getByteTimeDomainData(this.buffer);
    let sum = 0;
    for (const sample of this.buffer) {
      const centred = (sample - 128) / 128;
      sum += centred * centred;
    }
    const rms = Math.sqrt(sum / this.buffer.length);
    const target = Math.min(1, rms * 4);
    this.smoothed = target > this.smoothed ? target : this.smoothed * 0.85 + target * 0.15;
    return this.smoothed;
  }

  disconnect(): void {
    this.source.disconnect();
  }
}

/** Keeps the screen awake during a conversation, re-acquiring after the tab is shown again. */
export class ScreenWakeLock {
  private sentinel: WakeLockSentinel | null = null;
  private wanted = false;

  static get supported(): boolean {
    return typeof navigator !== "undefined" && "wakeLock" in navigator;
  }

  async acquire(): Promise<void> {
    this.wanted = true;
    if (!ScreenWakeLock.supported || this.sentinel || document.visibilityState !== "visible") return;
    try {
      this.sentinel = await navigator.wakeLock.request("screen");
      this.sentinel.addEventListener("release", () => {
        this.sentinel = null;
      });
    } catch {
      this.sentinel = null; // e.g. battery saver; the conversation carries on regardless
    }
  }

  async release(): Promise<void> {
    this.wanted = false;
    const sentinel = this.sentinel;
    this.sentinel = null;
    await sentinel?.release().catch(() => undefined);
  }

  /** Call when the page becomes visible again: the browser drops the lock when hidden. */
  async refresh(): Promise<void> {
    if (this.wanted) await this.acquire();
  }
}

/** Lock-screen / notification-area controls while a conversation is active. */
export function setMediaSession(active: boolean, handlers: { mute: () => void; end: () => void }): void {
  if (!("mediaSession" in navigator)) return;
  try {
    if (!active) {
      navigator.mediaSession.metadata = null;
      navigator.mediaSession.setActionHandler("pause", null);
      navigator.mediaSession.setActionHandler("stop", null);
      return;
    }
    navigator.mediaSession.metadata = new MediaMetadata({ title: tr("copy.talking_with_adapt_93ecb3e"), artist: tr("copy.adapt_2e26648") });
    navigator.mediaSession.setActionHandler("pause", handlers.mute);
    navigator.mediaSession.setActionHandler("stop", handlers.end);
  } catch {
    /* unsupported action on this platform */
  }
}
