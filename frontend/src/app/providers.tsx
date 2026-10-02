import { localize, useLocale } from "@/i18n";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { TooltipProvider } from "@/components/ui/Controls";
import { ApiError } from "@/lib/api/errors";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      retry: (failureCount, error) => {
        if (error instanceof Error && error.name === "CapabilityUnavailableError") return false;
        return error instanceof ApiError ? error.isRetryable && failureCount < 2 : failureCount < 1;
      },
      // In-memory only: server state (which may include private data) is never persisted.
      gcTime: 10 * 60_000,
    },
    mutations: { retry: false },
  },
});

export function Providers({ children }: { children: ReactNode }) {
  useLocale();
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>{localize(children)}</TooltipProvider>
    </QueryClientProvider>
  );
}
