import { tr } from "@/i18n";
import type { StreamCredential } from "./types";

export interface TranslationEvent { type: string; delta?: string; event_id?: string; session?: { expires_at?: number }; error?: { code?: string; message?: string } }
export function parseTranslationEvent(data: unknown): TranslationEvent | null {
  if (typeof data !== "string" || data.length > 100_000) return null;
  try {
    const e = JSON.parse(data);
    if (!e || typeof e.type !== "string" || (e.delta !== undefined && typeof e.delta !== "string")) return null;
    return e;
  } catch { return null; }
}
export interface TranslationConnection {
  connect(credential: StreamCredential, track: MediaStreamTrack, signal: AbortSignal): Promise<void>;
  close(): void;
}
export interface ConnectionCallbacks {
  event: (event: TranslationEvent) => void;
  remote: (stream: MediaStream) => void;
  lost: () => void;
}

/** One source speaker per peer connection. No standard voice-agent event lifecycle. */
export class WebRTCTranslationConnection implements TranslationConnection {
  private pc: RTCPeerConnection | null = null;
  private channel: RTCDataChannel | null = null;
  private closed = false;
  private grace: ReturnType<typeof setTimeout> | undefined;
  private cancel: (() => void) | undefined;
  constructor(private callbacks: ConnectionCallbacks) {}
  async connect(credential: StreamCredential, track: MediaStreamTrack, signal: AbortSignal): Promise<void> {
    if (credential.webrtc_url !== "https://api.openai.com/v1/realtime/translations/calls" || !/^ek[_-]/.test(credential.client_secret ?? "")) throw new Error(tr("copy.the_translation_endpoint_or_session_credential_i_ca5dee8"));
    if ((credential.credential_expires_at ?? 0) <= Date.now() / 1000) throw new Error(tr("copy.the_translation_credential_expired_start_again_t_059534c"));
    const abort = new AbortController();
    const deadline = setTimeout(() => abort.abort(), 20_000);
    const cancel = () => abort.abort(); signal.addEventListener("abort", cancel, { once: true });
    this.cancel = cancel;
    if (signal.aborted) abort.abort();
    const pc = this.pc = new RTCPeerConnection();
    const channel = this.channel = pc.createDataChannel("oai-events");
    pc.addTrack(track, new MediaStream([track]));
    pc.ontrack = (event) => this.callbacks.remote(event.streams[0] ?? new MediaStream([event.track]));
    let ready = false;
    let resolveReady: () => void = () => undefined;
    let rejectReady: (error: Error) => void = () => undefined;
    const opened = new Promise<void>((resolve, reject) => { resolveReady = resolve; rejectReady = reject; });
    // Attach immediately: session.created can arrive before setRemoteDescription resolves.
    // Catch immediately too, so a failed SDP request cannot leave an unhandled rejection.
    void opened.catch(() => undefined);
    const onAbort = () => rejectReady(new Error(tr("copy.translation_connection_was_interrupted_or_timed__ff540c3")));
    abort.signal.addEventListener("abort", onAbort, { once: true });
    channel.onmessage = ({ data }) => {
      const event = parseTranslationEvent(data); if (!event) return;
      if (event.type === "session.created") { ready = true; resolveReady(); }
      if (event.type === "error" && !ready) rejectReady(new Error(tr("copy.the_translation_service_could_not_start_this_ses_bbe24fd")));
      this.callbacks.event(event);
    };
    const lost = () => { if (!this.closed) { this.close(); this.callbacks.lost(); } };
    channel.onclose = () => ready ? lost() : rejectReady(new Error(tr("copy.the_translation_service_closed_the_connection_5b24a7e")));
    pc.onconnectionstatechange = () => {
      if (pc.connectionState === "connected") { clearTimeout(this.grace); this.grace = undefined; }
      else if (pc.connectionState === "disconnected") this.grace ??= setTimeout(lost, 4000);
      else if (pc.connectionState === "failed") { if (ready) lost(); else rejectReady(new Error(tr("copy.the_audio_connection_failed_8797514"))); }
    };
    try {
      await pc.setLocalDescription(await pc.createOffer());
      const response = await fetch(credential.webrtc_url, {
        method: "POST", headers: { Authorization: `Bearer ${credential.client_secret}`, "Content-Type": "application/sdp" },
        body: pc.localDescription?.sdp, signal: abort.signal, credentials: "omit", cache: "no-store", redirect: "error",
      });
      if (!response.ok) throw new Error(response.status === 401 ? tr("copy.the_session_credential_expired_please_start_agai_9d81696") : tr("copy.could_not_connect_to_realtime_translation_try_ag_437a2c3"));
      await pc.setRemoteDescription({ type: "answer", sdp: await response.text() });
      if (abort.signal.aborted || this.closed) throw new Error(tr("copy.translation_connection_was_cancelled_c31a4bb"));
      await opened;
    } catch (error) { this.close(); throw error; }
    finally { clearTimeout(deadline); signal.removeEventListener("abort", cancel); abort.signal.removeEventListener("abort", onAbort); this.cancel = undefined; }
  }
  close(): void {
    if (this.closed) return; this.closed = true; this.cancel?.(); clearTimeout(this.grace);
    if (this.channel) { this.channel.onmessage = null; this.channel.onclose = null; this.channel.close(); }
    if (this.pc) { this.pc.ontrack = null; this.pc.onconnectionstatechange = null; this.pc.close(); }
  }
}
