/**
 * Pure pieces of the voice session's control flow (unit tested).
 */

/**
 * Tracks the tool calls of a Realtime response and says when to ask the model to continue.
 *
 * The model finishes a response containing function calls. ADAPT runs each call on the
 * backend, adds each output to the conversation, and sends a single `response.create`
 * once every call has an output and the response is done. If the person starts speaking
 * in the meantime, their turn triggers the next response through voice activity detection,
 * so ADAPT does not send its own and the model doesn't answer twice.
 */
export class ToolTurn {
  private readonly seen = new Set<string>();
  private readonly pending = new Set<string>();
  private responseOpen = false;
  private hadCalls = false;
  private userSpoke = false;

  responseStarted(): void {
    // A response that starts while our tool calls are still running was triggered by the
    // person (voice activity detection): it will answer, so ADAPT must not add another.
    if (this.hadCalls && !this.responseOpen) this.userSpoke = true;
    else if (!this.hadCalls) this.userSpoke = false;
    this.responseOpen = true;
  }

  /** True when the call is new and should run (events can repeat a call id). */
  begin(callId: string): boolean {
    if (this.seen.has(callId)) return false;
    this.seen.add(callId);
    this.pending.add(callId);
    this.hadCalls = true;
    return true;
  }

  /** Output delivered. True when ADAPT should now send `response.create`. */
  finish(callId: string): boolean {
    this.pending.delete(callId);
    return this.settle();
  }

  /** The response ended. True when ADAPT should now send `response.create`. */
  responseDone(): boolean {
    this.responseOpen = false;
    return this.settle();
  }

  userSpeech(): void {
    if (this.hadCalls || this.responseOpen) this.userSpoke = true;
  }

  get running(): number {
    return this.pending.size;
  }

  reset(): void {
    this.pending.clear();
    this.responseOpen = false;
    this.hadCalls = false;
    this.userSpoke = false;
  }

  private settle(): boolean {
    if (!this.hadCalls || this.pending.size > 0 || this.responseOpen) return false;
    const shouldContinue = !this.userSpoke;
    this.hadCalls = false;
    this.userSpoke = false;
    return shouldContinue;
  }
}

export const MAX_RECONNECT_ATTEMPTS = 5;

/** Exponential backoff with jitter: about 1 s, 2 s, 4 s, 8 s, then 15 s. */
export function reconnectDelay(attempt: number, random: () => number = Math.random): number {
  const base = Math.min(15_000, 1_000 * 2 ** Math.max(0, attempt - 1));
  return Math.round(base * (0.8 + 0.4 * random()));
}

const HEADSET = /head(set|phone)|ear(bud|phone)|airpods|buds|bluetooth|hands-?free|bose|jabra|sony wh/i;

/** Noise-reduction profile from the audio devices in use (labels are available once the
 * microphone is allowed). Phones held close and headsets are near-field. */
export function audioProfileFor(labels: string[], coarsePointer: boolean): "near_field" | "far_field" {
  if (labels.some((label) => HEADSET.test(label))) return "near_field";
  return coarsePointer ? "near_field" : "far_field";
}
