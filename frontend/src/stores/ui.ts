import { create } from "zustand";
import { persist } from "zustand/middleware";

export type ThemePreference = "system" | "light" | "dark";

interface UiState {
  /** The assistant: right-side panel on desktop, bottom sheet on phones. */
  assistantOpen: boolean;
  searchOpen: boolean;
  theme: ThemePreference;
  setAssistantOpen: (open: boolean) => void;
  toggleAssistant: () => void;
  setSearchOpen: (open: boolean) => void;
  setTheme: (theme: ThemePreference) => void;
}

/**
 * Client-only UI state. Only non-sensitive preferences are persisted (theme).
 * Never put user facts, documents or journey data here: those are server state
 * (TanStack Query, in memory) and must not reach localStorage.
 */
export const useUiStore = create<UiState>()(
  persist(
    (set, get) => ({
      assistantOpen: false,
      searchOpen: false,
      theme: "system",
      setAssistantOpen: (assistantOpen) => set({ assistantOpen }),
      toggleAssistant: () => set({ assistantOpen: !get().assistantOpen }),
      setSearchOpen: (searchOpen) => set({ searchOpen }),
      setTheme: (theme) => {
        applyTheme(theme);
        set({ theme });
      },
    }),
    {
      name: "adapt.ui",
      partialize: (state) => ({ theme: state.theme }),
      onRehydrateStorage: () => (state) => state && applyTheme(state.theme),
    },
  ),
);

export function applyTheme(theme: ThemePreference): void {
  const root = document.documentElement;
  try {
    if (theme === "system") {
      delete root.dataset.theme;
      localStorage.removeItem("adapt.theme");
    } else {
      root.dataset.theme = theme;
      localStorage.setItem("adapt.theme", theme);
    }
  } catch {
    // Storage blocked: the theme still applies for this visit.
  }
}
