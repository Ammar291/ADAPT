import { create } from "zustand";
import {
  conversationReducer,
  initialConversation,
  type ConversationAction,
  type ConversationState,
} from "./conversation";

interface VoiceStore extends ConversationState {
  dispatch: (action: ConversationAction) => void;
}

/**
 * The live conversation, in memory only. It is never persisted: transcripts and tool
 * results can contain private information.
 */
export const useVoiceStore = create<VoiceStore>()((set) => ({
  ...initialConversation,
  dispatch: (action) => set((state) => conversationReducer(state, action)),
}));

export const dispatch = (action: ConversationAction) => useVoiceStore.getState().dispatch(action);
export const conversation = (): ConversationState => useVoiceStore.getState();
