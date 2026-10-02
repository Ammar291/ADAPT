import { tr, localize, useLocale } from "@/i18n";
import { Landmark } from "lucide-react";
import { useCallback, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { Segmented } from "@/components/ui/Controls";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/States";
import { useGovernanceGraph } from "@/lib/api/hooks";
import { useIsDesktop } from "@/lib/hooks/useMediaQuery";
import { GraphExplorer } from "./explorer/GraphExplorer";
import { useMapAspect } from "./explorer/hooks";
import { GovernanceDetails } from "./governance/GovernanceDetails";
import { GovernanceLegend, GovernanceNode, governanceMinimapColor } from "./governance/GovernanceNode";
import { GOVERNANCE_FILTERS, GOVERNANCE_GROUPS, buildGovernanceMap, filterGroups, requiresUaePass, type GovernanceFilter } from "./governance/model";

const nodeTypes = { governance: GovernanceNode };

function GovernanceSkeleton() {
  useLocale();
  const columns = [4, 7, 9, 6, 5];
  return (
    <div role="status" aria-label={tr("copy.loading_the_governance_graph_fd75603")} className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-col gap-3 border-b border-line px-4 py-3 sm:px-6 @3xl/main:flex-row @3xl/main:items-center lg:px-8">
        <Skeleton className="h-10 w-full @3xl/main:w-80" />
        <Skeleton className="h-9 w-full max-w-md" />
      </div>
      <div className="canvas-dots flex h-[62dvh] min-h-[420px] gap-6 overflow-hidden bg-canvas px-6 py-10 lg:h-auto lg:flex-1 lg:gap-14 lg:px-12">
        {columns.map((count, i) => (
          <div key={i} className="flex flex-1 flex-col justify-center gap-3">
            <Skeleton className="mb-3 h-4 w-2/3" />
            {localize(Array.from({ length: count }, (_, j) => (
              <Skeleton key={j} className="h-9 w-full rounded-[5px]" />
            )))}
          </div>
        ))}
      </div>
    </div>
  );
}

/** The public governance graph: Abu Dhabi's services, documents, rules, channels and authorities. */
export default function GovernanceGraphPage() {
  const uiLocale = useLocale();
  const graph = useGovernanceGraph();
  const [params, setParams] = useSearchParams();
  const [filter, setFilter] = useState<GovernanceFilter>("all");
  const rootRef = useRef<HTMLDivElement>(null);
  const isDesktop = useIsDesktop();
  const aspect = useMapAspect(rootRef, isDesktop);

  const map = useMemo(() => (graph.data && aspect ? buildGovernanceMap(graph.data, aspect) : null), [graph.data, aspect, uiLocale]);
  const nodesById = useMemo(() => new Map((graph.data?.nodes ?? []).map((n) => [n.id, n])), [graph.data, uiLocale]);
  const itemsById = useMemo(() => new Map((map?.items ?? []).map((i) => [i.id, i])), [map, uiLocale]);
  const selectedKey = params.get("node");
  const selectedId = useMemo(() => map?.items.find((i) => i.key === selectedKey)?.id ?? null, [map, selectedKey, uiLocale]);

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

  const servicesHeader = map?.headers.find((h) => h.id === "header:services");
  const keepGroups = useMemo(() => filterGroups(filter), [filter, uiLocale]);

  let body;
  if (graph.isError) {
    body = <ErrorState className="m-4 sm:m-6 lg:m-8" error={graph.error} onRetry={() => void graph.refetch()} />;
  } else if (!map) {
    body = <GovernanceSkeleton />;
  } else if (map.items.length === 0) {
    body = (
      <EmptyState
        className="m-4 sm:m-6 lg:m-8"
        icon={<Landmark className="size-5" aria-hidden />}
        title={tr("copy.no_public_rules_loaded_yet_12f5f10")}
        description={tr("copy.abu_dhabi_s_services_documents_and_authorities_a_7b071f1")}
      />
    );
  } else {
    body = (
      <GraphExplorer
        label={tr("copy.abu_dhabi_governance_graph_86f337e")}
        tone="governance"
        items={map.items}
        edges={map.edges}
        headers={map.headers}
        groups={GOVERNANCE_GROUPS}
        nodeTypes={nodeTypes}
        selectedId={selectedId}
        onSelect={onSelect}
        keepGroups={keepGroups}
        phoneStart={servicesHeader ? { rect: servicesHeader.rect, align: "top" } : null}
        searchPlaceholder={tr("copy.search_services_documents_authorities_6584b63")}
        minimapColor={governanceMinimapColor}
        legend={(markers) => <GovernanceLegend markers={markers} />}
        controls={
          <Segmented
            label={tr("copy.show_d97d1ee")}
            size="sm"
            value={filter}
            onChange={setFilter}
            options={GOVERNANCE_FILTERS.map((f) => ({ value: f.value, label: f.label }))}
          />
        }
        listMeta={(item) => {
          const node = nodesById.get(item.id);
          return node && requiresUaePass(node) ? <span>{tr("copy.needs_uae_pass_b8c7c6b")}</span> : null;
        }}
        details={(item, jump) => {
          const node = nodesById.get(item.id)!;
          return {
            title: item.label,
            caption: item.typeLabel,
            body: <GovernanceDetails node={node} onJump={jump} canJump={(id) => itemsById.has(id)} />,
          };
        }}
      />
    );
  }

  return (
    <div ref={rootRef} className="flex min-h-0 flex-1 flex-col">
      {localize(body)}
    </div>
  );
}
