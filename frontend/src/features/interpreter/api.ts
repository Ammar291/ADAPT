import { tr } from "@/i18n";
import { api } from "@/lib/api/client";
import type { Capabilities, Pair, RecordingResult, Session, Speaker } from "./types";

export interface InterpreterApi {
  capabilities(): Promise<Capabilities>;
  create(pair: Pair & { recorded?: boolean }, signal: AbortSignal): Promise<Session>;
  reconnect(id: string, signal: AbortSignal): Promise<Session>;
  end(id: string): Promise<void>;
  recording(id: string, speaker: Speaker, blob: Blob, signal: AbortSignal): Promise<RecordingResult>;
  text(pair: Pair, text: string, signal: AbortSignal): Promise<RecordingResult>;
}
export const interpreterApi: InterpreterApi = {
  text: (pair, text, signal) => api.post("/interpreter/text", { ...pair, text }, { signal, timeoutMs: 60_000 }),
  capabilities: () => api.get("/interpreter/capabilities"),
  create: (pair, signal) => api.post("/interpreter/session", pair, { signal }),
  reconnect: (session_id, signal) => api.post("/interpreter/reconnect", { session_id }, { signal }),
  end: (session_id) => api.post("/interpreter/end", { session_id }),
  recording: (id, speaker, blob, signal) => {
    const data = new FormData();
    data.append("session_id", id); data.append("speaker", speaker);
    data.append("audio", blob, blob.type.includes("mp4") ? "speech.m4a" : "speech.webm");
    return api.post("/interpreter/recording", data, { signal, timeoutMs: 90_000 });
  },
};

// Explicit demo selection only: no network, no microphone, no claimed live translation.
export const demoCapabilities: Capabilities = {
  provider: "demo", model: "gpt-realtime-translate", mode: "demo", fallback_enabled: true,
  languages: [
    { code: "en", name: tr("copy.english_649df08", { lng: "en" }), input: true, output: true, fallback: true, rtl: false },
    { code: "ar", name: tr("copy.arabic_af4f476", { lng: "en" }), input: true, output: false, fallback: true, rtl: true },
    { code: "hi", name: tr("copy.hindi_c9e6b25", { lng: "en" }), input: true, output: true, fallback: true, rtl: false },
  ],
  note: tr("copy.scripted_samples_only_no_microphone_audio_is_cap_2465916", { lng: "en" }),
  source: "https://developers.openai.com/cookbook/examples/voice_solutions/realtime_translation_guide",
};
export const demoApi: InterpreterApi = {
  text: async () => { throw new Error(tr("interpreter.textUnavailable")); },
  capabilities: async () => demoCapabilities,
  create: async (pair) => ({ session_id: "local-demo", mode: "demo", expires_at: Date.now() / 1000 + 3600, streams: [
    { ...pair, speaker: "a", transport: "demo" },
    { source: pair.target, target: pair.source, speaker: "b", transport: "demo" },
  ] }),
  reconnect: async () => { throw new Error(tr("copy.restart_the_demo_to_reconnect_8526abd")); },
  end: async () => undefined,
  recording: async () => { throw new Error(tr("copy.demo_mode_does_not_translate_recordings_da3efcd")); },
};
