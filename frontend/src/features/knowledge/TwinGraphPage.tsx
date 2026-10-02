import { tr, localize, useLocale } from "@/i18n";
import { Lock, UserRound } from "lucide-react";
import { useCallback, useMemo, useRef } from "react";
import { Link, useSearchParams } from "react-router";
import { buttonClass } from "@/components/ui/Button";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/States";
import { useDemo, useUserGraph } from "@/lib/api/hooks";
import { useIsDesktop } from "@/lib/hooks/useMediaQuery";
import { GraphExplorer } from "./explorer/GraphExplorer";
import type { ExplorerItem } from "./explorer/model";
import { useMapAspect } from "./explorer/hooks";
import { TwinDetails } from "./twin/TwinDetails";
import { PublicRuleNode, TwinLegend, TwinNode, twinMinimapColor } from "./twin/TwinNode";
import { TWIN_GROUPS, buildTwinMap, linkedPublicNodes } from "./twin/model";

const nodeTypes = { twin: TwinNode, public: PublicRuleNode };

/** Tab order for the radial map: the person first, then outwards ring by ring, clockwise from the top. */
function clockwise(a: ExplorerItem, b: ExplorerItem): number {
  const rank = (i: ExplorerItem) => (i.extra.centre === true ? 0 : i.nodeType === "public" ? 3 : i.type === "person" ? 1 : 2);
  const angle = (i: ExplorerItem) => {
    const a = Math.atan2(i.rect.y + i.rect.height / 2, i.rect.x + i.rect.width / 2) + Math.PI / 2;
    return a < 0 ? a + Math.PI * 2 : a;
  };
  return rank(a) - rank(b) || angle(a) - angle(b);
}

function PrivacyNote() {
  useLocale();
  return (
    <p className="flex items-center gap-2 border-b border-line bg-primary-tint/60 px-4 py-2 text-xs text-ink sm:px-6 lg:px-8">
      <Lock className="size-3.5 shrink-0 text-primary-strong" aria-hidden />
      {tr("copy.only_you_can_see_your_twin_it_s_stored_separatel_1853b62")}</p>
  );
}

function TwinSkeleton() {
  useLocale();
  const ring = Array.from({ length: 8 }, (_, i) => (i / 8) * Math.PI * 2);
  return (
    <div role="status" aria-label={tr("copy.loading_your_digital_twin_34d6a04")} className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-col gap-3 border-b border-line px-4 py-3 sm:px-6 @3xl/main:flex-row lg:px-8">
        <Skeleton className="h-10 w-full @3xl/main:w-80" />
      </div>
      <div className="relative h-[62dvh] min-h-[420px] overflow-hidden bg-muted-surface lg:h-auto lg:flex-1">
        <Skeleton className="absolute top-1/2 left-1/2 h-12 w-44 -translate-x-1/2 -translate-y-1/2 rounded-full" />
        {ring.map((a, i) => (
          <div
            key={i}
            aria-hidden
            className="absolute h-9 w-36 -translate-x-1/2 -translate-y-1/2 animate-pulse rounded-full bg-sunken"
            style={{ left: `${50 + Math.cos(a) * 32}%`, top: `${50 + Math.sin(a) * 32}%` }}
          />
        ))}
      </div>
    </div>
  );
}

/** The private digital twin: what ADAPT knows about you and your move, linked to the public rules. */
export default function TwinGraphPage() {
  const uiLocale = useLocale();
  const graph = useUserGraph();
  const demo = useDemo();
  const [params, setParams] = useSearchParams();
  const rootRef = useRef<HTMLDivElement>(null);
  const isDesktop = useIsDesktop();
  const aspect = useMapAspect(rootRef, isDesktop);

  const map = useMemo(() => (graph.data && graph.data.nodes.length && aspect ? buildTwinMap(graph.data, aspect) : null), [graph.data, aspect, uiLocale]);
  const nodesById = useMemo(() => {
    const data = graph.data;
    return new Map(data ? [...data.nodes, ...linkedPublicNodes(data)].map((n) => [n.id, n]) : []);
  }, [graph.data, uiLocale]);
  const itemsById = useMemo(() => new Map((map?.items ?? []).map((i) => [i.id, i])), [map, uiLocale]);
  const selectedKey = params.get("node");
  const selectedId = useMemo(() => {
    if (!map || !selectedKey) return null;
    // Twin keys and public keys live in different graphs; prefer the person's own node.
    return (map.items.find((i) => i.key === selectedKey && i.nodeType === "twin") ?? map.items.find((i) => i.key === selectedKey))?.id ?? null;
  }, [map, selectedKey, uiLocale]);

  const onSelect = useCallback(
    (id: string | null) => {
      const key = id ? itemsById.get(id)?.key : null;
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (key) next.set("node", key);
          else next.delete("node");
          return next;
        },
        { replace: true },
      );
    },
    [itemsById, setParams, uiLocale],
  );

  const centre = map?.items.find((i) => i.id === map.centreId);

  let body;
  if (graph.isError) {
    body = <ErrorState className="m-4 sm:m-6 lg:m-8" error={graph.error} onRetry={() => void graph.refetch()} />;
  } else if (graph.isPending || (graph.data.nodes.length > 0 && !map)) {
    body = <TwinSkeleton />;
  } else if (!map) {
    body = (
      <div className="px-4 py-6 sm:px-6 lg:px-8">
        <EmptyState
          icon={<UserRound className="size-5" aria-hidden />}
          title={tr("copy.your_twin_is_empty_for_now_cb39f8a")}
          description={tr("copy.it_fills_in_as_you_describe_your_move_and_confir_88b1a05")}
          action={
            <div className="flex flex-wrap items-center gap-4">
              <Link to="/onboarding" className={buttonClass("primary", "lg")}>
                {tr("copy.plan_my_move_7da4bc0")}</Link>
              {demo && (
                <button type="button" onClick={() => demo.seedSample.mutate()} className="text-sm text-muted underline underline-offset-4 hover:text-ink">
                  {tr("copy.explore_with_a_sample_plan_99cef7e")}</button>
              )}
            </div>
          }
        />
      </div>
    );
  } else {
    body = (
      <GraphExplorer
        label={tr("copy.my_digital_twin_a9d459f")}
        tone="twin"
        items={map.items}
        edges={map.edges}
        groups={TWIN_GROUPS}
        nodeTypes={nodeTypes}
        selectedId={selectedId}
        onSelect={onSelect}
        notice={<PrivacyNote />}
        phoneStart={centre ? { rect: centre.rect, align: "center" } : null}
        tabOrder={clockwise}
        searchPlaceholder={tr("copy.search_your_twin_4484c11")}
        minimapColor={twinMinimapColor}
        legend={(markers) => <TwinLegend markers={markers} />}
        listMeta={(item) => (item.extra.needsReview === true ? <span className="text-primary-strong">{tr("copy.needs_your_review_29dac63")}</span> : null)}
        details={(item, jump) => ({
          title: item.label,
          caption: item.typeLabel,
          body: <TwinDetails node={nodesById.get(item.id)!} graph={graph.data} onJump={jump} />,
        })}
      />
    );
  }

  return (
    <div ref={rootRef} className="flex min-h-0 flex-1 flex-col">
      {localize(body)}
    </div>
  );
}
