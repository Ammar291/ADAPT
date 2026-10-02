import { graphA11y } from "@/i18n/graphA11y";
import { tr, localize, useLocale } from "@/i18n";
/**
 * The journey as a transit map (React Flow). Layout, edge routes, filtering and highlighting come
 * from the pure functions in `layout.ts`, `routing.ts` and `graph.ts`; this component only renders
 * them and handles pointer, keyboard and viewport behaviour.
 */
import {
  Controls,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  useViewport,
  type NodeHandle,
} from "@xyflow/react";
import { useReducedMotion } from "motion/react";
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { LIFE_AREA_LABEL } from "@/domain/common";
import type { Journey, JourneyNode } from "@/domain/journey";
import { laneColor } from "@/components/ui/AreaLabel";
import { STATUS_LABEL, criticalPath, type JourneyFilter } from "@/lib/journey/analysis";
import { cn } from "@/lib/cn";
import {
  ARROW_DIRECTION,
  anyOfSizes,
  clampViewport,
  criticalEdges,
  edgeVisual,
  filterMatches,
  focusSet,
  initialViewport,
  neighbour,
  nodeEmphasis,
} from "./graph";
import { LAYOUT, columnX, type PlacedNode, type TransitLayout } from "./layout";
import { roundedPath, routeEdges } from "./routing";
import { edgeTypes, type TransitFlowEdge } from "./MapEdges";
import { dueText, nodeTypes, type MapFlowNode } from "./MapNodes";
import { EDGE_COLOR, KIND_LABEL } from "./visuals";

/** Screen space kept clear for the sticky line labels at the start of the canvas. */
const LABEL_SPACE = 140;
/** The stage ruler across the top of the canvas, and room kept below it. */
const RULER_HEIGHT = 30;
const RULER_SPACE = 44;
const MIN_READABLE_ZOOM = 0.72;

function handlesOf(placed: PlacedNode): NodeHandle[] {
  const { width: w, height: h } = placed;
  const handles: NodeHandle[] = [
    { id: "in", type: "target", position: Position.Left, x: 0, y: h / 2 - 0.5, width: 1, height: 1 },
    { id: "out", type: "source", position: Position.Right, x: w - 1, y: h / 2 - 0.5, width: 1, height: 1 },
    { id: "down", type: "target", position: Position.Bottom, x: w / 2 - 0.5, y: h - 1, width: 1, height: 1 },
  ];
  if (placed.role === "satellite") handles.push({ id: "up", type: "source", position: Position.Top, x: w / 2 - 0.5, y: 0, width: 1, height: 1 });
  return handles;
}

function ariaLabelOf(node: JourneyNode, critical: boolean): string {
  const due = dueText(node);
  return [
    node.title,
    KIND_LABEL[node.kind],
    STATUS_LABEL[node.status],
    `${LIFE_AREA_LABEL[node.area]} line`,
    critical ? tr("copy.on_the_critical_path_bcb7d9f") : null,
    due?.text ?? null,
  ]
    .filter(Boolean)
    .join(". ");
}

function stageLabel(column: number): string {
  return column === 0 ? tr("copy.can_start_now_0e49f9f") : `Stage ${column + 1}`;
}

/** Band backgrounds and the coloured lines, drawn under edges and stations. */
function LaneLayer({ layout }: { layout: TransitLayout }) {
  useLocale();
  const { x, y, zoom } = useViewport();
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 z-[2] overflow-hidden">
      <div className="absolute top-0 left-0 origin-top-left" style={{ transform: `translate(${x}px, ${y}px) scale(${zoom})` }}>
        {layout.bands.map((band) => (
          <div key={band.area}>
            <div
              className={cn("absolute border-t border-line", band.index % 2 === 1 && "bg-muted-surface")}
              style={{ left: -6000, top: band.y, width: layout.width + 12000, height: band.height }}
            />
            <div
              className="absolute rounded-full"
              style={{
                left: 24,
                top: band.lineY - 2,
                width: band.lineEnd - 24,
                height: 4,
                background: laneColor(band.area),
                opacity: 0.28,
              }}
            />
          </div>
        ))}
      </div>
    </div>
  );
}

/** Line names pinned to the start of the canvas, and stage names pinned to its top. */
function StickyLabels({ layout }: { layout: TransitLayout }) {
  useLocale();
  const { x, y, zoom } = useViewport();
  const columns = Array.from({ length: layout.columns }, (_, i) => i);
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 z-[5] overflow-hidden">
      {/* Once the map is panned, the labels pin to the edge: give them a quiet gutter so
          stations slide under it instead of peeking out around each label. */}
      {x + 14 * zoom < 10 && <div className="absolute inset-y-0 left-0 w-[138px] border-e border-line bg-canvas/90 backdrop-blur-[2px]" />}
      {layout.bands.map((band) => (
        <div
          key={band.area}
          className="absolute top-0 left-0 flex w-[118px] items-center gap-2 rounded-lg border border-line bg-surface py-1.5 ps-2 pe-2.5 shadow-card"
          style={{ transform: `translate(${Math.max(10, x + 14 * zoom)}px, ${y + band.lineY * zoom}px) translateY(-50%)` }}
        >
          <span className="h-7 w-1 shrink-0 rounded-full" style={{ background: laneColor(band.area) }} />
          <span className="min-w-0">
            <span className="block truncate text-sm leading-4 font-medium text-ink">{localize(LIFE_AREA_LABEL[band.area])}</span>
            <span className="tabular mt-0.5 block text-2xs text-subtle">
              {localize(band.done)} {tr("copy.of_2449d65")}{localize(band.total)} {tr("copy.done_e5fd9cf")}</span>
          </span>
        </div>
      ))}
      <div className="absolute inset-x-0 top-0 border-b border-line bg-canvas" style={{ height: RULER_HEIGHT }}>
        {columns.map((column) => (
          <span
            key={column}
            className="absolute top-1/2 left-0 text-2xs font-medium whitespace-nowrap text-muted"
            style={{ transform: `translate(-50%, -50%) translateX(${x + (columnX(column) + LAYOUT.stationWidth / 2) * zoom}px)` }}
          >
            {localize(stageLabel(column))}
          </span>
        ))}
      </div>
    </div>
  );
}

interface TransitMapProps {
  journey: Journey;
  layout: TransitLayout;
  filter: JourneyFilter;
  selectedKey: string | null;
  onSelect: (key: string | null) => void;
  /** Desktop: minimap and wheel-to-scroll. */
  desktop: boolean;
  className?: string;
}

function MapCanvas({ journey, layout, filter, selectedKey, onSelect, desktop, className }: TransitMapProps) {
  const uiLocale = useLocale();
  const flow = useReactFlow<MapFlowNode, TransitFlowEdge>();
  const wrapper = useRef<HTMLDivElement>(null);
  const reduceMotion = useReducedMotion();
  const [hovered, setHovered] = useState<string | null>(null);
  const duration = reduceMotion ? 0 : 320;

  const byKey = useMemo(() => new Map(journey.nodes.map((n) => [n.key, n])), [journey, uiLocale]);
  const critical = useMemo(() => criticalPath(journey), [journey, uiLocale]);
  const criticalSet = useMemo(() => new Set(critical), [critical, uiLocale]);
  const criticalEdgeIds = useMemo(() => criticalEdges(journey, critical), [journey, critical, uiLocale]);
  const sizes = useMemo(() => anyOfSizes(journey), [journey, uiLocale]);
  const matches = useMemo(() => filterMatches(journey, filter), [journey, filter, uiLocale]);
  const focusKey = selectedKey ?? hovered;
  const focus = useMemo(() => (focusKey && byKey.has(focusKey) ? focusSet(journey, focusKey) : null), [journey, byKey, focusKey, uiLocale]);

  const nodes = useMemo<MapFlowNode[]>(
    () =>
      layout.nodes.map((placed) => {
        const node = byKey.get(placed.key)!;
        const emphasis = nodeEmphasis(placed.key, focus, matches);
        return {
          id: placed.key,
          type: placed.role,
          position: { x: placed.x, y: placed.y },
          width: placed.width,
          height: placed.height,
          measured: { width: placed.width, height: placed.height },
          handles: handlesOf(placed),
          data: { node, emphasis, critical: criticalSet.has(placed.key) },
          ariaLabel: ariaLabelOf(node, criticalSet.has(placed.key)),
          draggable: false,
          selectable: false,
          connectable: false,
          zIndex: emphasis === "focused" ? 3 : emphasis === "related" ? 2 : 1,
        } as MapFlowNode;
      }),
    [layout, byKey, focus, matches, criticalSet, uiLocale],
  );

  const routes = useMemo(() => routeEdges(journey, layout), [journey, layout, uiLocale]);
  const edges = useMemo<TransitFlowEdge[]>(() => {
    const ctx = { nodes: byKey, critical: criticalEdgeIds, focus, matches, anyOfSizes: sizes };
    return journey.edges.flatMap((edge) => {
      const route = routes.get(edge.id);
      if (!route) return [];
      const visual = edgeVisual(edge, ctx);
      return [
        {
          id: edge.id,
          type: "transit" as const,
          // Arrows run from the prerequisite to the step that needs it.
          source: edge.target,
          target: edge.source,
          sourceHandle: route.vertical ? "up" : "out",
          targetHandle: route.vertical ? "down" : "in",
          data: { visual, path: roundedPath(route.points), label: route.label },
          markerEnd: { type: MarkerType.ArrowClosed, color: EDGE_COLOR[visual.tone], width: 14, height: 14 },
          zIndex: visual.tone === "focus" ? 2 : visual.dimmed ? 0 : 1,
          selectable: false,
          focusable: false,
        },
      ];
    });
  }, [journey, routes, byKey, criticalEdgeIds, focus, matches, sizes, uiLocale]);

  /** The part of the canvas nothing covers: right of the line labels, left of an overlaid panel. */
  const visibleArea = useCallback(() => {
    const rect = wrapper.current?.getBoundingClientRect();
    if (!rect) return null;
    const panel = document.querySelector("[data-journey-panel]")?.getBoundingClientRect();
    const right = panel && panel.left < rect.right && panel.right > rect.left ? panel.left - rect.left : rect.width;
    return { left: LABEL_SPACE, right: Math.max(LABEL_SPACE + 120, right), top: RULER_SPACE, bottom: rect.height };
  }, [uiLocale]);

  const center = useCallback(
    (key: string, animate: boolean) => {
      const placed = layout.byKey.get(key);
      const area = visibleArea();
      if (!placed || !area) return;
      const zoom = Math.max(flow.getViewport().zoom, 0.85);
      const screenX = (area.left + area.right) / 2;
      const screenY = (area.top + area.bottom) / 2;
      const target = clampViewport(
        { zoom, x: screenX - (placed.x + placed.width / 2) * zoom, y: screenY - (placed.y + placed.height / 2) * zoom },
        { width: layout.width, height: layout.height },
        { right: area.right, bottom: area.bottom, top: RULER_SPACE },
      );
      void flow.setViewport(target, { duration: animate ? duration : 0 });
    },
    [flow, layout, duration, visibleArea, uiLocale],
  );

  const ensureVisible = useCallback(
    (key: string) => {
      const placed = layout.byKey.get(key);
      const area = visibleArea();
      if (!placed || !area) return;
      const { x, y, zoom } = flow.getViewport();
      const left = placed.x * zoom + x;
      const top = placed.y * zoom + y;
      const margin = 16;
      const visible =
        left >= area.left &&
        left + placed.width * zoom <= area.right - margin &&
        top >= area.top &&
        top + placed.height * zoom <= area.bottom - margin;
      if (!visible) center(key, true);
    },
    [flow, layout, center, visibleArea, uiLocale],
  );

  // Open at the start of every line; once open, centre the step that was already selected
  // (deep links, or switching from the list), then keep later selections in view.
  const [ready, setReady] = useState(false);
  const onInit = useCallback(() => {
    const rect = wrapper.current?.getBoundingClientRect();
    if (!rect) return;
    const viewport = initialViewport(
      { width: layout.width, height: layout.height + RULER_SPACE },
      { width: rect.width, height: rect.height },
      { minZoom: MIN_READABLE_ZOOM, maxZoom: 1 },
    );
    void flow.setViewport({ ...viewport, y: viewport.y + RULER_SPACE * viewport.zoom });
    setReady(true);
  }, [flow, layout, uiLocale]);

  const centerFirst = useRef(Boolean(selectedKey));
  useEffect(() => {
    if (!selectedKey || !ready) return;
    // Wait for the details panel to finish opening beside the map.
    const timer = window.setTimeout(
      () => {
        if (centerFirst.current) {
          centerFirst.current = false;
          center(selectedKey, false);
        } else {
          ensureVisible(selectedKey);
        }
      },
      reduceMotion ? 30 : 300,
    );
    return () => window.clearTimeout(timer);
  }, [selectedKey, ready, center, ensureVisible, reduceMotion]);

  const focusNode = useCallback((key: string) => {
    const element = wrapper.current?.querySelector<HTMLElement>(`.react-flow__node[data-id="${CSS.escape(key)}"]`);
    element?.focus();
  }, [uiLocale]);

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const element = (event.target as HTMLElement).closest<HTMLElement>(".react-flow__node");
    const key = element?.dataset.id;
    if (!key || !layout.byKey.has(key)) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onSelect(key);
      return;
    }
    const direction = ARROW_DIRECTION[event.key];
    if (direction) {
      event.preventDefault();
      const next = neighbour(layout.nodes, key, direction);
      if (next) {
        focusNode(next);
        ensureVisible(next);
      }
    }
  };

  return (
    <div
      ref={wrapper}
      dir="ltr"
      className={cn("adapt-flow relative", className)}
      onKeyDown={onKeyDown}
      role="region"
      aria-label={tr("copy.journey_map_tab_to_a_step_use_the_arrow_keys_to__465a9c3")}
    >
      <ReactFlow<MapFlowNode, TransitFlowEdge>
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onInit={onInit}
        onNodeClick={(_, node) => onSelect(node.id)}
        onNodeMouseEnter={(_, node) => setHovered(node.id)}
        onNodeMouseLeave={() => setHovered(null)}
        onPaneClick={() => onSelect(null)}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        nodesFocusable
        edgesFocusable={false}
        panOnScroll={desktop}
        zoomOnScroll={!desktop}
        zoomOnDoubleClick={false}
        minZoom={0.25}
        maxZoom={1.6}
        translateExtent={[
          [-600, -400],
          [layout.width + 600, layout.height + 400],
        ]}
        deleteKeyCode={null}
        selectionKeyCode={null}
        multiSelectionKeyCode={null}
        panActivationKeyCode={null}
        attributionPosition="bottom-left"
        ariaLabelConfig={graphA11y()}
      >
        <LaneLayer layout={layout} />
        <StickyLabels layout={layout} />
        <Controls
          position="top-right"
          orientation="horizontal"
          showInteractive={false}
          fitViewOptions={{ padding: 0.06, duration }}
          style={{ marginTop: RULER_HEIGHT + 12 }}
        />
        {desktop && !selectedKey && (
          <MiniMap<MapFlowNode>
            position="top-right"
            pannable
            zoomable
            nodeColor={(n) => laneColor(n.data.node.area)}
            nodeBorderRadius={8}
            className="hidden! @5xl/main:block!"
            style={{ width: 168, height: 132, marginTop: RULER_HEIGHT + 12 + 44 }}
          />
        )}
      </ReactFlow>
    </div>
  );
}

export function TransitMap(props: TransitMapProps) {
  useLocale();
  return (
    <ReactFlowProvider>
      <MapCanvas {...props} />
    </ReactFlowProvider>
  );
}
