/**
 * Public surface of the voice / assistant feature.
 *
 * Hosts lazy-load the panel so WebRTC and audio code stays out of the main bundle:
 *   const ConversationPanel = lazy(() => import("@/features/voice/ConversationPanel"));
 * The store and selectors are light and safe to import eagerly (e.g. to pulse a button
 * while a call is live):
 *   import { useVoiceStore } from "@/features/voice/store";
 *   import { selectIsLive } from "@/features/voice/selectors";
 */
export type { PanelVariant } from "./ConversationPanel";
export type { ApprovalItem, ConversationItem, ConversationState, Phase, ToolItem } from "./conversation";
export { derivePhase } from "./conversation";
export {
  selectActions,
  selectCitations,
  selectIsLive,
  selectPendingApprovals,
  selectRunningTool,
  type ConversationAction,
  type ConversationCitation,
} from "./selectors";
export { useVoiceStore } from "./store";
