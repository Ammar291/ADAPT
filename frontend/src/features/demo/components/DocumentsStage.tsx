import { tr, localize, useLocale } from "@/i18n";
import { BadgeCheck, Check, ExternalLink, FileText, ScanText } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Badge } from "@/components/ui/Badge";
import { Spinner } from "@/components/ui/Spinner";
import type { ExtractedField, UserDocument } from "@/domain/documents";
import type { KnowledgeGraph, KnowledgeNode } from "@/domain/graph";
import type { RunEvent } from "@/domain/runs";
import type { ScenarioDocument } from "@/domain/scenario";
import { useDocument } from "@/features/documents/hooks";
import { useUserGraph } from "@/lib/api/hooks";
import { cn } from "@/lib/cn";
import { formatDuration } from "@/lib/format";
import { useServices } from "@/services/context";
import { describeMethod, doneCount, pipelineFromEvents } from "../pipeline";
import { STAGE_PACE_MS } from "../useFounderArrival";

/** Every event of a run, replayed from the start and then live. */
function useRunEventList(runId: string | null | undefined): RunEvent[] {
  const services = useServices();
  const [events, setEvents] = useState<RunEvent[]>([]);
  useEffect(() => {
    setEvents([]);
    if (!runId) return;
    return services.runs.subscribe(runId, {
      onEvent: (event) => setEvents((list) => (list.some((e) => e.seq === event.seq) ? list : [...list, event])),
      onState: () => undefined,
    });
  }, [runId, services]);
  return events;
}

/** Counts up to `target` one step at a time, so stages light up in a readable sequence. */
function usePaced(target: number, ms = STAGE_PACE_MS): number {
  const [shown, setShown] = useState(0);
  useEffect(() => {
    if (shown >= target) {
      if (shown > target) setShown(target);
      return;
    }
    const timer = setTimeout(() => setShown((n) => n + 1), shown === 0 ? 120 : ms);
    return () => clearTimeout(timer);
  }, [shown, target, ms]);
  return shown;
}

function Confidence({ value }: { value: number }) {
  useLocale();
  const percent = Math.round(value * 100);
  return (
    <span className="flex items-center gap-1.5" title={localize(tr("copy.adapt_is_v0_sure_of_this_value_278ed7a", { v0: percent }))}>
      <span className="h-1.5 w-12 overflow-hidden rounded-full bg-sunken" aria-hidden>
        <span className={cn("block h-full rounded-full", value >= 0.85 ? "bg-primary" : "bg-dune")} style={{ width: `${percent}%` }} />
      </span>
      <span className="tabular text-2xs text-muted">{localize(percent)}{tr("copy.text_4345cb1")}</span>
    </span>
  );
}

function DocumentReading({ doc, upload, index }: { doc: ScenarioDocument; upload: UserDocument | undefined; index: number }) {
  const uiLocale = useLocale();
  const detail = useDocument(upload?.id ?? null, upload?.status);
  const events = useRunEventList(upload?.extractionRunId);
  const pipeline = useMemo(
    () => pipelineFromEvents(events, { uploaded: Boolean(upload), detail: upload ? `${upload.filename} received` : null }),
    [events, upload, uiLocale],
  );
  const shown = usePaced(doneCount(pipeline));
  const current = detail.data ?? upload;
  // What the reader scored, kept from before Kabir confirmed (confirming makes every value certain).
  const [firstRead, setFirstRead] = useState<ExtractedField[] | null>(null);
  const read = current?.extraction?.fields ?? [];
  useEffect(() => {
    if (!firstRead && current?.status === "extracted" && read.length) setFirstRead(read);
  }, [firstRead, current?.status, read]);
  const fields = shown >= 3 ? (firstRead ?? read) : [];
  const confirmed = current?.status === "confirmed";

  return (
    <article className="grid gap-5 rounded-xl border border-line bg-surface p-4 md:grid-cols-[minmax(0,12rem)_minmax(0,1fr)]" aria-label={localize(doc.title)}>
      <div className="flex flex-col gap-2">
        <div className="relative aspect-[595/842] overflow-hidden rounded-md border border-line bg-sunken">
          <iframe title={localize(tr("copy.synthetic_v0_d773328", { v0: doc.title.toLowerCase() }))} src={`${doc.url}#toolbar=0&navpanes=0&view=FitH`} className="absolute inset-0 size-full" loading="lazy" />
        </div>
        <a href={doc.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-2xs text-muted underline-offset-4 hover:text-ink hover:underline">
          {tr("copy.open_the_synthetic_pdf_b864984")}<ExternalLink className="size-3" aria-hidden />
          <span className="sr-only">{tr("copy.opens_in_a_new_tab_bf5b990")}</span>
        </a>
      </div>
      <div className="flex min-w-0 flex-col gap-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="grid size-7 place-items-center rounded-full bg-sunken text-xs font-medium tabular">{localize(index + 1)}</span>
          <h3 className="text-base font-medium">{localize(doc.title)}</h3>
          {confirmed && (
            <Badge tone="primary" icon={<BadgeCheck className="size-3.5" aria-hidden />}>
              {tr("copy.confirmed_by_kabir_148af95")}</Badge>
          )}
        </div>
        <ol className="grid grid-cols-2 gap-2 lg:grid-cols-4" aria-live="polite">
          {pipeline.stages.map((stage, i) => {
            const lit = i < shown;
            const active = upload && i === shown && !pipeline.failed;
            return (
              <li
                key={stage.stage}
                className={cn(
                  "flex flex-col gap-1 rounded-lg border p-2.5 transition-colors duration-300",
                  lit ? "border-primary/50 bg-primary-tint" : "border-line bg-muted-surface",
                )}
              >
                <span className="flex items-center gap-1.5 text-xs font-medium">
                  {lit ? <Check className="size-3.5 text-primary" aria-hidden /> : active ? <Spinner className="size-3.5" /> : <span className="size-3.5 rounded-full border border-line-strong" aria-hidden />}
                  {localize(stage.label)}
                </span>
                <span className="text-2xs text-muted">{lit ? (stage.detail ?? tr("copy.done_e9b450d")) : active ? tr("copy.working_3b4dfc9") : tr("copy.waiting_33d3063")}</span>
                {lit && stage.durationMs !== null && <span className="text-2xs text-subtle tabular">{localize(formatDuration(stage.durationMs))}</span>}
              </li>
            );
          })}
        </ol>
        {pipeline.failed && <p className="text-sm text-danger">{localize(pipeline.failed)}</p>}
        {fields.length > 0 ? (
          <div>
            <p className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-muted">
              <ScanText className="size-3.5" aria-hidden />
              {localize(describeMethod(current?.extractionMethod, current?.mrzVerified))}
            </p>
            <dl className="divide-y divide-line rounded-lg border border-line">
              {fields.map((field) => (
                <div key={field.name} className="grid grid-cols-[minmax(7rem,11rem)_minmax(0,1fr)_auto] items-center gap-3 px-3 py-1.5 text-sm">
                  <dt className="text-muted">{localize(field.label)}</dt>
                  <dd className="font-medium break-words">{localize(field.value ?? tr("copy.not_printed_f781f6e"))}</dd>
                  <dd>
                    <Confidence value={field.confidence} />
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        ) : (
          <ul className="flex flex-col gap-1 text-sm text-muted">
            {doc.reads.map((line) => (
              <li key={line} className="flex gap-2">
                <FileText className="mt-0.5 size-3.5 shrink-0 text-subtle" aria-hidden />
                {localize(line)}
              </li>
            ))}
          </ul>
        )}
        <p className="rounded-md bg-sunken px-3 py-2 text-sm">{localize(doc.changes)}</p>
      </div>
    </article>
  );
}

const TYPE_LABEL: Record<string, string> = {
  person: tr("copy.kabir_0adae93", { lng: "en" }),
  spouse: tr("copy.spouse_04aee08", { lng: "en" }),
  nationality: tr("copy.nationality_1969ead", { lng: "en" }),
  passport: tr("copy.passport_d5ed1ca", { lng: "en" }),
  document: tr("copy.document_e214b8a", { lng: "en" }),
  company: tr("copy.company_7a19949", { lng: "en" }),
  business_activity: tr("copy.activity_81c0d91", { lng: "en" }),
  goal: tr("copy.goal_9fe00ac", { lng: "en" }),
  language: tr("copy.language_89b86ab", { lng: "en" }),
  household: tr("copy.household_52996fa", { lng: "en" }),
  community_preference: tr("copy.community_bfd58ee", { lng: "en" }),
};

function fromDocument(node: KnowledgeNode): boolean {
  return Object.values(node.facts).some((f) => f.source === "document_extracted");
}

/** The private twin: what Kabir stated, and (ringed) what was read from his documents. */
function TwinGrowth({ graph }: { graph: KnowledgeGraph }) {
  const uiLocale = useLocale();
  const width = 540;
  const height = 440;
  const cx = width / 2;
  const cy = height / 2;
  const hub = graph.nodes.find((n) => n.type === "person") ?? graph.nodes[0];
  const placed = useMemo(() => {
    if (!hub) return [];
    const direct = new Set(graph.edges.filter((e) => e.source === hub.id).map((e) => e.target));
    const ring1 = graph.nodes.filter((n) => direct.has(n.id)).sort((a, b) => a.type.localeCompare(b.type) || a.label.localeCompare(b.label));
    const positions = new Map<string, { x: number; y: number; angle: number }>();
    positions.set(hub.id, { x: cx, y: cy, angle: 0 });
    ring1.forEach((node, i) => {
      const angle = (i / Math.max(ring1.length, 1)) * Math.PI * 2 - Math.PI / 2;
      positions.set(node.id, { x: cx + Math.cos(angle) * 105, y: cy + Math.sin(angle) * 100, angle });
    });
    const rest = graph.nodes.filter((n) => !positions.has(n.id)).sort((a, b) => a.type.localeCompare(b.type) || a.label.localeCompare(b.label));
    const siblings = new Map<string, number>();
    for (const node of rest) {
      const parent = graph.edges.find((e) => e.target === node.id && positions.has(e.source));
      const base = parent ? positions.get(parent.source)!.angle : 0;
      const n = siblings.get(parent?.source ?? "") ?? 0;
      siblings.set(parent?.source ?? "", n + 1);
      const angle = base + (n % 2 === 0 ? 1 : -1) * (0.16 + 0.2 * Math.floor(n / 2));
      positions.set(node.id, { x: cx + Math.cos(angle) * 178, y: cy + Math.sin(angle) * 168, angle });
    }
    return graph.nodes.map((node) => ({ node, ...positions.get(node.id)! }));
  }, [graph, hub, cx, cy, uiLocale]);
  const at = new Map(placed.map((p) => [p.node.id, p]));
  const read = graph.nodes.filter(fromDocument).length;

  return (
    <figure className="flex flex-col gap-2 rounded-xl border border-line bg-surface p-4">
      <figcaption className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-base font-medium">{tr("copy.kabir_s_private_twin_ccf74d2")}</span>
        <span className="text-xs text-muted">
          {localize(graph.nodes.length)} {tr("copy.entities_266b9f6")}{localize(read)} {tr("copy.read_from_documents_05ec49a")}</span>
      </figcaption>
      <svg viewBox={`-90 0 ${width + 180} ${height}`} className="w-full" role="img" aria-label={localize(tr("copy.private_user_graph_with_v0_entities_v1_read_from_c46f167", { v0: graph.nodes.length, v1: read }))}>
        {graph.edges.map((edge) => {
          const a = at.get(edge.source);
          const b = at.get(edge.target);
          return a && b ? <line key={edge.id} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="var(--line-strong)" strokeWidth={1} /> : null;
        })}
        {placed.map(({ node, x, y, angle }) => {
          const isHub = node.id === hub?.id;
          const doc = fromDocument(node);
          const cos = Math.cos(angle);
          // Labels sit outside the node, on the side facing away from the centre.
          const anchor = isHub ? "middle" : cos > 0.1 ? "start" : cos < -0.1 ? "end" : "middle";
          const lx = isHub ? x : x + (anchor === "start" ? 13 : anchor === "end" ? -13 : 0);
          const ly = isHub ? y + 36 : anchor === "middle" ? y + (Math.sin(angle) > 0 ? 24 : -16) : y + 4;
          const text = isHub ? tr("copy.kabir_0adae93") : node.label || TYPE_LABEL[node.type] || node.type;
          return (
            <g key={node.id}>
              {doc && !isHub && <circle cx={x} cy={y} r={13} fill="none" stroke="var(--teal)" strokeOpacity={0.3} strokeWidth={4} />}
              <circle cx={x} cy={y} r={isHub ? 20 : 8} fill={isHub ? "var(--ink)" : doc ? "var(--teal)" : "var(--surface)"} stroke={doc ? "var(--teal)" : "var(--ink-subtle)"} strokeWidth={1.5} />
              <text x={lx} y={ly} textAnchor={anchor} fontSize={isHub ? 14 : 12} fill={doc ? "var(--ink)" : "var(--ink-muted)"}>
                {text.length > 24 ? `${text.slice(0, 23)}…` : text}
              </text>
            </g>
          );
        })}
      </svg>
      <p className="flex flex-wrap gap-x-4 gap-y-1 text-2xs text-muted">
        <span className="inline-flex items-center gap-1.5">
          <span className="size-2.5 rounded-full bg-primary" aria-hidden /> {tr("copy.read_from_a_document_f8a81df")}</span>
        <span className="inline-flex items-center gap-1.5">
          <span className="size-2.5 rounded-full border border-subtle bg-surface" aria-hidden /> {tr("copy.stated_by_kabir_0c74341")}</span>
      </p>
    </figure>
  );
}

export function DocumentsStage({ docs }: { docs: { doc: ScenarioDocument; upload: UserDocument | undefined }[] }) {
  useLocale();
  const graph = useUserGraph();
  return (
    <div className="grid gap-4 min-[1900px]:grid-cols-[minmax(0,1fr)_34rem]">
      <div className="flex flex-col gap-4">
        {docs.map(({ doc, upload }, index) => (
          <DocumentReading key={doc.key} doc={doc} upload={upload} index={index} />
        ))}
      </div>
      <div className="min-[1900px]:sticky min-[1900px]:top-16 min-[1900px]:self-start">
        {graph.data && graph.data.nodes.length > 0 && <TwinGrowth graph={graph.data} />}
      </div>
    </div>
  );
}
