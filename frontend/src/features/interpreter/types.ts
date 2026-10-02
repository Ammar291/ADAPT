export type Speaker = "a" | "b";
export type InterpreterState = "idle" | "connecting" | "listening" | "translating" | "speaking" | "paused" | "reconnecting" | "stopped" | "error";
export type InterpreterEventName = "interpreter_started" | "speaker_detected" | "translation_started" | "translation_received" | "audio_playing" | "translation_completed" | "reconnecting" | "interpreter_error" | "interpreter_stopped";
export interface Language { code: string; name: string; input: boolean; output: boolean; fallback: boolean; rtl: boolean }
export interface Capabilities { provider: string; model: string; mode: "live" | "demo" | "unavailable"; languages: Language[]; fallback_enabled: boolean; note: string; source: string }
export interface Pair { source: string; target: string }
export interface StreamCredential extends Pair { speaker: Speaker; transport: "webrtc" | "recorded" | "demo"; client_secret?: string | null; credential_expires_at?: number | null; session_expires_at?: number | null; webrtc_url?: string | null }
export interface Session { session_id: string; mode: "live" | "demo"; expires_at: number; streams: StreamCredential[] }
export interface RecordingResult { speaker: Speaker; original: string; translation: string; audio_base64?: string | null; audio_mime: string; audio_error?: string | null }
export interface Transcript { original: string; translation: string }
export interface Snapshot { state: InterpreterState; active: Speaker; muted: boolean; paused: boolean; mode: "live" | "demo" | null; transcripts: Record<Speaker, Transcript>; transports: Record<Speaker, StreamCredential["transport"]>; error: string | null; notice: string | null; playbackBlocked: boolean; recording: boolean; replayable: Record<Speaker, boolean>; level: number }
export interface InterpreterEvent { name: InterpreterEventName; speaker?: Speaker; state: InterpreterState; timestamp: number; demo: boolean; code?: string }
