/**
 * The action-card vocabulary, shared by every screen that shows a prepared action.
 *
 *   Prepared           ADAPT drafted it; nothing has been sent
 *   Approval required  it waits for the person's decision
 *   Official handoff   the person completes it on the official site (ADAPT can't submit)
 *   Demo adapter       a simulated service produced the preview (example slots, a check)
 *
 * There is deliberately no "Submitted" label here: an action only gets past a handoff with
 * the person's own confirmation or a real external reference, and screens that show that
 * say where it came from.
 */
import type { ActionKind, ActionStatus } from "@/domain/common";
import type { ApprovalStatus } from "@/domain/documents";

export type ActionCardLabel = "Prepared" | "Approval required" | "Official handoff" | "Demo adapter";

export interface ActionCardInput {
  status: ActionStatus;
  kind: ActionKind;
  isSimulated: boolean;
  /** The decision on its approval, when it has one. */
  approvalStatus?: ApprovalStatus | null;
}

export function actionCardLabels(action: ActionCardInput): ActionCardLabel[] {
  const labels: ActionCardLabel[] = [];
  if (action.status === "prepared") labels.push("Prepared");
  if (action.status === "awaiting_approval" || (action.approvalStatus === "pending" && action.status !== "handoff_required")) {
    labels.push("Approval required");
  }
  if (action.kind === "official_handoff" || action.status === "handoff_required") labels.push("Official handoff");
  if (action.isSimulated) labels.push("Demo adapter");
  return labels;
}

export const ACTION_CARD_HINT: Record<ActionCardLabel, string> = {
  Prepared: "ADAPT drafted this. Nothing has been sent.",
  "Approval required": "Nothing happens until you approve it.",
  "Official handoff": "You complete this on the official site. ADAPT can't submit it for you.",
  "Demo adapter": "A simulated service made this preview. Nothing is booked or submitted.",
};
