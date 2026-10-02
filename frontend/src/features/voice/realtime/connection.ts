import { tr } from "@/i18n";
/**
 * One WebRTC call to the OpenAI Realtime API.
 *
 * The browser authenticates with the short-lived client secret minted by ADAPT's backend.
 * The session (model, instructions, tools) was fixed server-side when that secret was
 * created, so this class only moves audio and events. Audio flows over the media tracks;
 * events flow over the `oai-events` data channel.
 */
import type { ClientEvent, ServerEvent } from "./events";
import { parseServerEvent } from "./events";

export type ConnectFailure = "timeout" | "rejected" | "rate_limited" | "failed";

export class ConnectError extends Error {
  constructor(
    readonly reason: ConnectFailure,
    message: string,
  ) {
    super(message);
    this.name = "ConnectError";
  }
}

export interface ConnectOptions {
  clientSecret: string;
  webrtcUrl: string;
  microphone: MediaStreamTrack;
  audioElement: HTMLAudioElement;
  timeoutMs: number;
  onEvent: (event: ServerEvent) => void;
  /** The established call dropped (network change, server closed, ICE failure). */
  onLost: (reason: string) => void;
  /** The browser refused to start playback (autoplay policy): ask for a tap. */
  onAutoplayBlocked?: () => void;
}

/** How long ICE may stay "disconnected" before the call counts as lost (it often recovers). */
const DISCONNECT_GRACE_MS = 5_000;

export function isRealtimeEndpoint(url: string): boolean {
  return url === "https://api.openai.com/v1/realtime/calls";
}

export class RealtimeConnection {
  private closed = false;
  private established = false;
  private graceTimer: ReturnType<typeof setTimeout> | null = null;

  private constructor(
    private readonly pc: RTCPeerConnection,
    private readonly channel: RTCDataChannel,
    private readonly sender: RTCRtpSender,
    private readonly options: ConnectOptions,
  ) {}

  remoteStream: MediaStream | null = null;

  static async connect(options: ConnectOptions): Promise<RealtimeConnection> {
    if (!isRealtimeEndpoint(options.webrtcUrl)) {
      throw new ConnectError("rejected", tr("copy.the_voice_endpoint_is_not_trusted_c69b657"));
    }
    const deadline = AbortSignal.timeout(options.timeoutMs);
    const pc = new RTCPeerConnection();
    const channel = pc.createDataChannel("oai-events");
    const sender = pc.addTrack(options.microphone, new MediaStream([options.microphone]));
    const connection = new RealtimeConnection(pc, channel, sender, options);

    pc.ontrack = (event) => {
      const [stream] = event.streams;
      if (!stream) return;
      connection.remoteStream = stream;
      options.audioElement.srcObject = stream;
      void options.audioElement.play().catch(() => options.onAutoplayBlocked?.());
    };

    try {
      await pc.setLocalDescription(await pc.createOffer());
      let response: Response;
      try {
        response = await fetch(options.webrtcUrl, {
          method: "POST",
          body: pc.localDescription?.sdp,
          headers: { Authorization: `Bearer ${options.clientSecret}`, "Content-Type": "application/sdp" },
          signal: deadline,
          redirect: "error",
          credentials: "omit",
          cache: "no-store",
        });
      } catch {
        throw deadline.aborted
          ? new ConnectError("timeout", tr("copy.connecting_took_too_long_88477ee"))
          : new ConnectError("failed", tr("copy.couldn_t_reach_the_voice_service_65e4843"));
      }
      if (!response.ok) {
        if (response.status === 429) throw new ConnectError("rate_limited", tr("copy.voice_is_busy_right_now_5e97103"));
        if (response.status === 401 || response.status === 403) {
          throw new ConnectError("rejected", tr("copy.the_voice_session_expired_before_it_started_222af35"));
        }
        throw new ConnectError("failed", `The voice service answered ${response.status}`);
      }
      await pc.setRemoteDescription({ type: "answer", sdp: await response.text() });
      await connection.ready(deadline);
    } catch (error) {
      connection.close();
      throw error instanceof ConnectError ? error : new ConnectError("failed", tr("copy.voice_connection_failed_73e2b86"));
    }
    return connection;
  }

  /** Resolves once the data channel is open and the server has sent `session.created`. */
  private ready(deadline: AbortSignal): Promise<void> {
    return new Promise((resolve, reject) => {
      const fail = (error: ConnectError) => {
        cleanup();
        reject(error);
      };
      const onAbort = () => fail(new ConnectError("timeout", tr("copy.connecting_took_too_long_88477ee")));
      const cleanup = () => deadline.removeEventListener("abort", onAbort);
      if (deadline.aborted) return onAbort();
      deadline.addEventListener("abort", onAbort, { once: true });

      this.channel.onmessage = (message: MessageEvent) => {
        const event = parseServerEvent(message.data);
        if (!event) return;
        if (!this.established && event.type === "session.created") {
          this.established = true;
          cleanup();
          this.watch();
          resolve();
        }
        if (event.type === "error" && !this.established) {
          fail(new ConnectError("failed", event.error.message));
          return;
        }
        this.options.onEvent(event);
      };
      this.channel.onclose = () => {
        if (!this.established) fail(new ConnectError("failed", tr("copy.the_voice_service_closed_the_call_44a82e5")));
        else this.lost("channel_closed");
      };
    });
  }

  private watch(): void {
    this.pc.onconnectionstatechange = () => {
      const state = this.pc.connectionState;
      if (state === "connected") {
        if (this.graceTimer) clearTimeout(this.graceTimer);
        this.graceTimer = null;
      } else if (state === "disconnected") {
        this.graceTimer ??= setTimeout(() => this.lost("disconnected"), DISCONNECT_GRACE_MS);
      } else if (state === "failed" || state === "closed") {
        this.lost(state);
      }
    };
  }

  private lost(reason: string): void {
    if (this.closed) return;
    this.close();
    this.options.onLost(reason);
  }

  get isOpen(): boolean {
    return !this.closed && this.channel.readyState === "open";
  }

  /** Whether the underlying transport still works (checked when the page becomes visible). */
  get healthy(): boolean {
    return this.isOpen && !["failed", "closed"].includes(this.pc.connectionState);
  }

  send(event: ClientEvent): boolean {
    if (!this.isOpen) return false;
    this.channel.send(JSON.stringify(event));
    return true;
  }

  /** Swap the microphone without renegotiating (headset plugged in, track ended on lock). */
  async replaceMicrophone(track: MediaStreamTrack): Promise<void> {
    await this.sender.replaceTrack(track);
  }

  close(): void {
    if (this.closed) return;
    this.closed = true;
    if (this.graceTimer) clearTimeout(this.graceTimer);
    this.channel.onmessage = null;
    this.channel.onclose = null;
    this.pc.onconnectionstatechange = null;
    this.pc.ontrack = null;
    try {
      this.channel.close();
    } catch {
      /* already closed */
    }
    this.pc.close();
    if (this.options.audioElement.srcObject === this.remoteStream) this.options.audioElement.srcObject = null;
  }
}
