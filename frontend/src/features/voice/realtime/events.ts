/**
 * The subset of OpenAI Realtime (GA) data-channel events ADAPT uses.
 * Server events arrive on the `oai-events` data channel; client events are sent on it.
 */

interface Base {
  event_id?: string;
}

export interface FunctionCallItem {
  id?: string;
  type: "function_call";
  call_id: string;
  name: string;
  arguments?: string;
}

export interface MessageItem {
  id?: string;
  type: "message";
  role: "user" | "assistant" | "system";
}

export type OutputItem = FunctionCallItem | MessageItem | { id?: string; type: string };

export type ServerEvent =
  | (Base & { type: "session.created" | "session.updated"; session?: unknown })
  | (Base & { type: "input_audio_buffer.speech_started"; item_id: string; audio_start_ms?: number })
  | (Base & { type: "input_audio_buffer.speech_stopped"; item_id: string })
  | (Base & { type: "input_audio_buffer.committed"; item_id: string })
  | (Base & { type: "input_audio_buffer.timeout_triggered"; item_id?: string })
  | (Base & {
      type: "conversation.item.input_audio_transcription.delta";
      item_id: string;
      delta?: string | null;
    })
  | (Base & {
      type: "conversation.item.input_audio_transcription.completed";
      item_id: string;
      transcript: string;
    })
  | (Base & { type: "conversation.item.input_audio_transcription.failed"; item_id: string })
  | (Base & { type: "response.created"; response: { id: string } })
  | (Base & {
      type: "response.output_audio_transcript.delta" | "response.output_text.delta";
      response_id: string;
      item_id: string;
      delta: string;
    })
  | (Base & {
      type: "response.output_audio_transcript.done";
      response_id: string;
      item_id: string;
      transcript: string;
    })
  | (Base & { type: "response.output_text.done"; response_id: string; item_id: string; text: string })
  | (Base & { type: "response.output_item.added"; response_id: string; item: OutputItem })
  | (Base & {
      type: "response.function_call_arguments.done";
      response_id: string;
      item_id: string;
      call_id: string;
      name: string;
      arguments: string;
    })
  | (Base & {
      type: "response.done";
      response: {
        id: string;
        status?: "completed" | "cancelled" | "failed" | "incomplete" | "in_progress";
        output?: OutputItem[];
        status_details?: { reason?: string; error?: { code?: string; message?: string } | null } | null;
      };
    })
  | (Base & { type: "output_audio_buffer.started"; response_id?: string })
  | (Base & { type: "output_audio_buffer.stopped" | "output_audio_buffer.cleared"; response_id?: string })
  | (Base & {
      type: "error";
      error: { type?: string; code?: string | null; message: string; param?: string | null };
    })
  | (Base & { type: "rate_limits.updated" });

export type ServerEventType = ServerEvent["type"];

/** Client events ADAPT sends. */
export type ClientEvent =
  | {
      type: "conversation.item.create";
      item:
        | { type: "function_call_output"; call_id: string; output: string }
        | {
            type: "message";
            role: "user" | "system";
            content: Array<{ type: "input_text"; text: string }>;
          }
        | { type: "message"; role: "assistant"; content: Array<{ type: "output_text"; text: string }> };
    }
  | { type: "response.create"; response?: Record<string, unknown> }
  | { type: "response.cancel" }
  | { type: "output_audio_buffer.clear" }
  | {
      type: "session.update";
      session: { type: "realtime"; audio?: { input?: { noise_reduction?: { type: "near_field" | "far_field" } } } };
    };

const KNOWN = new Set<string>([
  "session.created",
  "session.updated",
  "input_audio_buffer.speech_started",
  "input_audio_buffer.speech_stopped",
  "input_audio_buffer.committed",
  "input_audio_buffer.timeout_triggered",
  "conversation.item.input_audio_transcription.delta",
  "conversation.item.input_audio_transcription.completed",
  "conversation.item.input_audio_transcription.failed",
  "response.created",
  "response.output_audio_transcript.delta",
  "response.output_audio_transcript.done",
  "response.output_text.delta",
  "response.output_text.done",
  "response.output_item.added",
  "response.function_call_arguments.done",
  "response.done",
  "output_audio_buffer.started",
  "output_audio_buffer.stopped",
  "output_audio_buffer.cleared",
  "error",
  "rate_limits.updated",
]);

/** Parse a data-channel message. Unknown or malformed events return null and are ignored. */
export function parseServerEvent(data: unknown): ServerEvent | null {
  if (typeof data !== "string") return null;
  try {
    const event = JSON.parse(data) as { type?: unknown };
    return typeof event.type === "string" && KNOWN.has(event.type) ? (event as ServerEvent) : null;
  } catch {
    return null;
  }
}
