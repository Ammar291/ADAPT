import { tr } from "@/i18n";
export class InterpreterAudioError extends Error {
  constructor(readonly code: string, message: string) { super(message); }
}
export function microphoneProblem(error: unknown): InterpreterAudioError {
  const name = error instanceof Error ? error.name : "";
  if (["NotAllowedError", "SecurityError"].includes(name)) return new InterpreterAudioError("mic_denied", tr("copy.microphone_access_was_denied_allow_it_in_your_br_b142181"));
  if (["NotFoundError", "OverconstrainedError"].includes(name)) return new InterpreterAudioError("mic_unavailable", tr("copy.that_microphone_is_unavailable_connect_a_microph_5317ff5"));
  return new InterpreterAudioError("mic_busy", tr("copy.the_microphone_could_not_start_close_other_apps__4dd808b"));
}
export async function captureMicrophone(deviceId?: string): Promise<MediaStream> {
  if (!window.isSecureContext) throw new InterpreterAudioError("insecure_context", tr("copy.microphone_access_requires_https_or_localhost_an_46e37d3"));
  if (!navigator.mediaDevices?.getUserMedia || typeof RTCPeerConnection === "undefined") throw new InterpreterAudioError("unsupported_browser", tr("copy.this_browser_cannot_run_the_realtime_interpreter_cbc46c7"));
  try {
    return await navigator.mediaDevices.getUserMedia({ video: false, audio: {
      echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1,
      ...(deviceId ? { deviceId: { exact: deviceId } } : {}),
    } });
  } catch (error) { throw microphoneProblem(error); }
}

export function recordingMime(): string | undefined {
  if (typeof MediaRecorder === "undefined") return undefined;
  return ["audio/webm;codecs=opus", "audio/mp4", "audio/ogg;codecs=opus"].find((type) => MediaRecorder.isTypeSupported(type));
}

/** Analyse a stream without connecting it to speakers. Never loop output into input. */
export class Meter {
  private source: MediaStreamAudioSourceNode;
  private analyser: AnalyserNode;
  private buffer: Uint8Array<ArrayBuffer>;
  constructor(context: AudioContext, stream: MediaStream) {
    this.source = context.createMediaStreamSource(stream);
    this.analyser = context.createAnalyser(); this.analyser.fftSize = 512;
    this.buffer = new Uint8Array(new ArrayBuffer(512)); this.source.connect(this.analyser);
  }
  level(): number {
    this.analyser.getByteTimeDomainData(this.buffer);
    let sum = 0; for (const value of this.buffer) sum += ((value - 128) / 128) ** 2;
    return Math.sqrt(sum / this.buffer.length);
  }
  close(): void { this.source.disconnect(); this.analyser.disconnect(); }
}
