/**
 * Frontend mock mode (the app running without its backend features): typed turns go to the
 * app's mock assistant service, and its deterministic events are folded into the same
 * conversation as live turns. Voice itself is never mocked: no speech is synthesised here.
 */
import type { AssistantEvent } from "@/domain/assistant";
import { currentServices } from "@/services/context";
import type { ToolCitation, VoiceToolCallResult } from "./types";
import { dispatch } from "./store";

/** The app's services say the assistant is mocked (no backend assistant to call). */
export function mockAssistantActive(): boolean {
  try {
    return currentServices().sources.assistant === "mock";
  } catch {
    return false; // services not bootstrapped: use the backend
  }
}

function result(callId: string, name: string, label: string, ok: boolean, summary: string | null, citations: ToolCitation[]): VoiceToolCallResult {
  const status = ok ? "ok" : "error";
  return {
    call_id: callId,
    name,
    status,
    output: {},
    activity: { call_id: callId, name, label, status, summary },
    approval: null,
    consent: null,
    citations,
    ui_hint: null,
  };
}

/** Runs one typed turn through the mock assistant. Returns the reply text. */
export async function runMockTurn(turnId: string, text: string, language: string | null): Promise<string> {
  const tools = new Map<string, { name: string; label: string; ok: boolean; summary: string | null; citations: ToolCitation[] }>();
  let lastTool: string | null = null;
  let reply = "";

  const refresh = (callId: string) => {
    const tool = tools.get(callId);
    if (tool) dispatch({ type: "tool_finished", result: result(callId, tool.name, tool.label, tool.ok, tool.summary, tool.citations) });
  };

  const events: AsyncIterable<AssistantEvent> = currentServices().assistant.respond(text, {
    route: window.location.pathname,
    channel: "text",
    language: language ?? "en",
  });
  for await (const event of events) {
    switch (event.type) {
      case "text_delta":
        reply += event.text;
        break;
      case "tool_call": {
        const callId = `${turnId}:${event.call.id}`;
        tools.set(callId, { name: event.call.name, label: event.call.label, ok: true, summary: null, citations: [] });
        lastTool = callId;
        dispatch({ type: "tool_started", callId, name: event.call.name, label: event.call.label });
        break;
      }
      case "tool_result": {
        const callId = `${turnId}:${event.callId}`;
        const tool = tools.get(callId);
        if (tool) {
          tool.ok = event.ok;
          tool.summary = event.summary;
          refresh(callId);
        }
        break;
      }
      case "citation": {
        const tool = lastTool ? tools.get(lastTool) : undefined;
        if (tool && lastTool) {
          tool.citations.push({
            title: event.citation.title,
            url: event.citation.url,
            authority: event.citation.authority,
            retrieved_at: event.citation.retrievedAt,
            kind: event.citation.kind,
          });
          refresh(lastTool);
        }
        break;
      }
      case "approval": {
        const approval = event.approval;
        dispatch({
          type: "approval_request",
          via: "mock",
          request: {
            action_id: approval.id,
            title: approval.title,
            summary: approval.summary,
            simulation_label: approval.simulationLabel,
            consequences: approval.consequences,
            requires_user_authentication: approval.requiresUserAuthentication,
            handoff_url: approval.officialUrl,
            kind: approval.actionKind,
          },
        });
        break;
      }
      case "error":
        throw new Error(event.message);
      default:
        break;
    }
  }
  return reply.trim();
}

/** Records a decision on a mock approval through the app's mock services. */
export async function decideMockApproval(approvalId: string, approve: boolean): Promise<{ status: string; handoffUrl: string | null }> {
  const approval = await currentServices().approvals.decide(approvalId, approve ? "approve" : "reject");
  return { status: approval.status, handoffUrl: approve ? approval.officialUrl : null };
}
