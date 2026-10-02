/**
 * Live adapter for scripted demo scenarios (`/api/demo/scenarios*`).
 *
 * The scenario kit serves fixed inputs; this adapter posts them, verbatim, to the same
 * public routes the app uses (onboarding, uploads, journeys, research). Everything that
 * is read back (documents, the plan, research, what-ifs, actions) goes through the normal
 * services, so the demo shows exactly what any user would see.
 */
import type { DocumentKind } from "@/domain/documents";
import type { DemoScenario, ScenarioRole } from "@/domain/scenario";
import { api } from "@/lib/api/client";
import { CATEGORY_SECTION } from "./research";

type Raw = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

export const scenarioPaths = {
  scenario: (key: string) => `/demo/scenarios/${encodeURIComponent(key)}`,
  onboarding: "/onboarding/profile",
  journeys: "/journey",
  research: "/research",
  logout: "/auth/logout",
} as const;

export interface ScenarioService {
  get(key: string, signal?: AbortSignal): Promise<DemoScenario>;
  /** The synthetic PDF as a file, ready for the normal upload. */
  documentFile(key: string, documentKey: string): Promise<File>;
  /** The persona's onboarding answers and consents (POST /onboarding/profile). */
  saveProfile(key: string): Promise<void>;
  /** A deterministic journey run over the given uploads. */
  startJourney(key: string, documentIds: string[]): Promise<{ runId: string; journeyId: string }>;
  /** Research on ADAPT's curated source list, for this plan. */
  startResearch(key: string, journeyId: string): Promise<{ jobId: string; runId: string }>;
  /** Ends this demo account's session; the next request starts a fresh private account. */
  freshStart(): Promise<void>;
}

/** Raw scripts by key: their bodies are posted as served, never re-shaped in the browser. */
const scripts = new Map<string, Raw>();

async function script(key: string, signal?: AbortSignal): Promise<Raw> {
  const known = scripts.get(key);
  if (known) return known;
  const raw = await api.get<Raw>(scenarioPaths.scenario(key), { signal });
  scripts.set(key, raw);
  return raw;
}

export function toScenario(raw: Raw): DemoScenario {
  return {
    key: raw.key,
    title: raw.title,
    tagline: raw.tagline,
    syntheticNotice: raw.synthetic_notice,
    persona: {
      name: raw.persona.name,
      headline: raw.persona.headline,
      summary: raw.persona.summary,
      facts: (raw.persona.facts ?? []).map((f: Raw) => ({
        label: f.label,
        value: f.value,
        source: f.source === "document" || f.source === "missing" ? f.source : "stated",
      })),
    },
    documents: (raw.documents ?? []).map((d: Raw) => ({
      key: d.key,
      kind: d.kind as DocumentKind,
      title: d.title,
      filename: d.filename,
      url: d.url,
      reads: d.reads ?? [],
      changes: d.changes ?? "",
      confirm: d.confirm !== false,
    })),
    researchGroups: (raw.research_groups ?? []).map((g: Raw) => ({
      key: g.key,
      title: g.title,
      description: g.description,
      sections: (g.categories ?? []).map((c: string) => CATEGORY_SECTION[c]).filter(Boolean),
    })),
    roles: (raw.roles ?? []).map((r: Raw) => ({ role: r.role as ScenarioRole, label: r.label, nodeKey: r.task_key, note: r.note })),
    whatIf: { key: raw.what_if.key, title: raw.what_if.title, description: raw.what_if.description },
    acts: raw.acts ?? [],
  };
}

export const liveScenarios: ScenarioService = {
  async get(key, signal) {
    return toScenario(await script(key, signal));
  },
  async documentFile(key, documentKey) {
    const doc: Raw | undefined = ((await script(key)).documents ?? []).find((d: Raw) => d.key === documentKey);
    if (!doc) throw new Error(`The scenario has no document '${documentKey}'`);
    // A same-origin path from the kit (synthetic content, nothing private): fetched as is.
    const response = await fetch(doc.url, { credentials: "same-origin", cache: "no-store" });
    if (!response.ok) throw new Error(`Couldn't load the synthetic ${doc.title.toLowerCase()} (${response.status})`);
    return new File([await response.blob()], doc.filename, { type: "application/pdf" });
  },
  async saveProfile(key) {
    await api.post<Raw>(scenarioPaths.onboarding, (await script(key)).onboarding);
  },
  async startJourney(key, documentIds) {
    const started = await api.post<Raw>(scenarioPaths.journeys, { ...(await script(key)).journey, document_ids: documentIds });
    return { runId: started.run.id, journeyId: started.journey_id };
  },
  async startResearch(key, journeyId) {
    const started = await api.post<Raw>(scenarioPaths.research, { ...(await script(key)).research, journey_id: journeyId });
    return { jobId: started.job.id, runId: started.job.run_id };
  },
  async freshStart() {
    scripts.clear();
    await api.post<void>(scenarioPaths.logout);
  },
};
