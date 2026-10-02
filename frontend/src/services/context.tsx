import { useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, type ReactNode } from "react";
import { TOPIC_KEYS } from "@/lib/api/queryKeys";
import type { AppServices } from "./registry";

const ServicesContext = createContext<AppServices | null>(null);

let current: AppServices | null = null;

/**
 * The resolved services, for non-React modules (e.g. the voice controller singleton).
 * Set by <ServicesProvider>; throws if called before the app has bootstrapped.
 */
export function currentServices(): AppServices {
  if (!current) throw new Error("Services are not ready yet");
  return current;
}

/** Provides the resolved services. */
export function ServicesProvider({ services, children }: { services: AppServices; children: ReactNode }) {
  current = services;
  return <ServicesContext.Provider value={services}>{children}</ServicesContext.Provider>;
}

/**
 * Keeps caches fresh while someone is signed in: when the data source reports a change (a
 * document finished processing, a run paused for approval, research finished), the matching
 * queries are invalidated and refetched from the server.
 */
export function useServerChanges(enabled: boolean): void {
  const services = useServices();
  const client = useQueryClient();
  useEffect(() => {
    if (!enabled || !services.onChange) return;
    return services.onChange((topics) => {
      for (const topic of topics) {
        for (const key of TOPIC_KEYS[topic] ?? []) void client.invalidateQueries({ queryKey: key });
      }
    });
  }, [enabled, services, client]);
}

export function useServices(): AppServices {
  const services = useContext(ServicesContext);
  if (!services) throw new Error("useServices must be used inside <ServicesProvider>");
  return services;
}
