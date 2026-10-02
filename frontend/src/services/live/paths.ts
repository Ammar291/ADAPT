/**
 * Every live API path in one place, relative to `config.apiBaseUrl` (`/api`). Feature
 * adapters owned by other workstreams keep their own path tables next to their adapter
 * (e.g. `researchPaths` in `./research.ts`).
 */
export const paths = {
  systemInfo: "/system/info",
  demoSession: "/auth/demo-session",
  logout: "/auth/logout",
  me: "/me",
  preferences: "/me/preferences",
  governanceGraph: "/graph/governance",
  governanceNode: (ref: string) => `/graph/governance/nodes/${encodeURIComponent(ref)}`,
  journeyTopology: "/agents/journey/topology",
  topology: (graph: string) => `/agents/${graph}/topology`,
  startRun: "/agents/run",
  runs: "/agents/runs",
  run: (id: string) => `/agents/${id}`,
  cancelRun: (id: string) => `/agents/${id}/cancel`,
  runEvents: (id: string) => `/agents/${id}/events`,
} as const;
