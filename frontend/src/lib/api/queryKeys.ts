/** Query-key factory: the single place that defines cache identity and invalidation scopes. */
export const queryKeys = {
  system: ["system", "info"] as const,
  me: ["me"] as const,
  governance: {
    all: ["governance"] as const,
    graph: (types: string[] = [], q = "") => ["governance", "graph", { types, q }] as const,
    node: (ref: string) => ["governance", "node", ref] as const,
  },
  workflow: (kind: string) => ["workflow", kind] as const,
  /** Everything under `private` belongs to the signed-in user and is cleared on sign-out. */
  private: {
    all: ["private"] as const,
    profile: ["private", "profile"] as const,
    journeys: ["private", "journeys"] as const,
    journey: (id: string) => ["private", "journey", id] as const,
    activeJourney: ["private", "journey", "active"] as const,
    runs: ["private", "runs"] as const,
    run: (id: string) => ["private", "runs", id] as const,
    review: (id: string) => ["private", "runs", id, "review"] as const,
    userGraph: ["private", "userGraph"] as const,
    documents: ["private", "documents"] as const,
    document: (id: string) => ["private", "documents", id] as const,
    generated: ["private", "generated"] as const,
    approvals: (status?: string) => ["private", "approvals", status ?? "all"] as const,
    approvalsAll: ["private", "approvals"] as const,
    actions: ["private", "actions"] as const,
    discoverItems: ["private", "discover", "items"] as const,
    discoverStatus: ["private", "discover", "status"] as const,
    discover: ["private", "discover"] as const,
  },
} as const;

/** Which caches a server-side change topic invalidates. */
export const TOPIC_KEYS: Record<string, readonly (readonly unknown[])[]> = {
  session: [queryKeys.me],
  profile: [queryKeys.private.profile],
  journeys: [queryKeys.private.journeys, ["private", "journey"], queryKeys.private.userGraph],
  runs: [queryKeys.private.runs],
  documents: [queryKeys.private.documents],
  generated: [queryKeys.private.generated],
  approvals: [queryKeys.private.approvalsAll, queryKeys.private.actions],
  discover: [queryKeys.private.discover],
  graph: [queryKeys.private.userGraph],
};
