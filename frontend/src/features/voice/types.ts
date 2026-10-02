/**
 * Voice contracts. Generated from `backend/app/contracts/voice.py` via `@adapt/contracts`;
 * re-exported here so the feature has one import site.
 */
export type {
  ApprovalRequest,
  AssistantMessageOut,
  AssistantMessageRequest,
  ConsentRequest,
  ConversationMessage,
  ToolActivity,
  ToolCitation,
  VoiceSessionOut,
  VoiceSessionRequest,
  VoiceToolCallRequest,
  VoiceToolCallResult,
  VoiceToolSpec,
} from "@adapt/contracts";

import type { VoiceToolCallResult } from "@adapt/contracts";

export type ToolStatus = VoiceToolCallResult["status"];
export type AudioProfile = "near_field" | "far_field";
