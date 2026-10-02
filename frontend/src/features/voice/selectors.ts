/**
 * Read-only views of the conversation for surfaces around the panel (the /assistant side
 * column, the floating button). Pure functions of the store state, safe to pass straight
 * to `useVoiceStore(selector)`: list results are memoised on the items array, so they keep
 * their identity until the conversation changes (zustand re-renders on every new object).
 */
import type { ApprovalItem, ConversationItem, ConversationState, ToolItem } from "./conversation";

function memoOnItems<T>(compute: (items: ConversationItem[]) => T): (state: ConversationState) => T {
  const cache = new WeakMap<ConversationItem[], T>();
  return (state) => {
    if (!cache.has(state.items)) cache.set(state.items, compute(state.items));
    return cache.get(state.items) as T;
  };
}

type EvidenceKind = "authoritative_requirement" | "official_guidance" | "community_web" | "ai_recommendation";

/** A source behind something ADAPT said, with its trust tier. */
export interface ConversationCitation {
  title: string;
  url: string;
  authority: string | null;
  retrievedAt: string | null;
  section: string | null;
  quote: string | null;
  kind: EvidenceKind;
}

/** Something ADAPT did, or the person decided, during the conversation. */
export interface ConversationAction {
  id: string;
  kind: "tool" | "approval";
  title: string;
  status: string;
  summary: string | null;
  /** Official page to continue on, only after the backend confirmed an approval. */
  handoffUrl: string | null;
}

const LIVE = new Set(["requesting_mic", "connecting", "connected", "reconnecting", "offline"]);

/** A voice call is in progress (possibly reconnecting). */
export function selectIsLive(state: ConversationState): boolean {
  return state.mode === "voice" && LIVE.has(state.connection);
}

export function selectRunningTool(state: ConversationState): ToolItem | null {
  for (let i = state.items.length - 1; i >= 0; i--) {
    const item = state.items[i];
    if (item?.kind === "tool" && item.status === "running") return item;
  }
  return null;
}

/** Every source cited so far, newest first, one entry per URL. */
export const selectCitations = memoOnItems((items): ConversationCitation[] => {
  const seen = new Map<string, ConversationCitation>();
  for (let i = items.length - 1; i >= 0; i--) {
    const item = items[i];
    if (item?.kind !== "tool") continue;
    for (const citation of item.citations) {
      if (seen.has(citation.url)) continue;
      seen.set(citation.url, {
        title: citation.title,
        url: citation.url,
        authority: citation.authority ?? null,
        retrievedAt: citation.retrieved_at ?? null,
        section: null,
        quote: null,
        kind: citation.kind,
      });
    }
  }
  return [...seen.values()];
});

export const selectPendingApprovals = memoOnItems((items): ApprovalItem[] =>
  items.filter(
    (item): item is ApprovalItem =>
      item.kind === "approval" && (item.state === "pending" || item.state === "submitting" || item.state === "failed"),
  ),
);

/** Finished tool work and decided approvals, oldest first. */
export const selectActions = memoOnItems((items): ConversationAction[] => {
  const actions: ConversationAction[] = [];
  for (const item of items) {
    if (item.kind === "tool" && item.status !== "running") {
      actions.push({
        id: item.id,
        kind: "tool",
        title: item.label,
        status: item.status,
        summary: item.summary,
        handoffUrl: null,
      });
    } else if (item.kind === "approval" && (item.state === "approved" || item.state === "declined")) {
      actions.push({
        id: item.id,
        kind: "approval",
        title: item.request.title,
        status: item.state,
        summary: item.outcome?.message ?? null,
        handoffUrl: item.outcome?.handoffUrl ?? null,
      });
    }
  }
  return actions;
});
