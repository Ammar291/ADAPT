import { graphA11y } from "@/i18n/graphA11y";
import { tr, localize, useLocale } from "@/i18n";
/**
 * The graph explorer shared by the public governance graph and the private twin: a React Flow
 * map with search, fit, zoom, legend, hover/selection highlighting and a details panel, plus
 * an accessible list view. Each page supplies its own layout, node look, legend and details.
 */
import { MiniMap, Panel, ReactFlow, ReactFlowProvider, useReactFlow, type NodeTypes } from "@xyflow/react";
import { Info, List, Network, X } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useCallback, useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent as ReactMouseEvent, type ReactNode } from "react";
import { IconButton } from "@/components/ui/Button";
import { Segmented } from "@/components/ui/Controls";
import { Sheet } from "@/components/ui/Sheet";
import { useIsDesktop } from "@/lib/hooks/useMediaQuery";
import { cn } from "@/lib/cn";
import { HeaderNode, Markers, RelationEdge, ZoomControls, ZoomSync, ZoomedInOnly, type KgFlowEdge, type KgFlowNode, type KgHeaderNode } from "./flow";
import { GraphList } from "./GraphList";
import { GraphSearch } from "./GraphSearch";
import { useElementSize, useSearchShortcut } from "./hooks";
import { boundsOf, type Rect } from "../layout/geometry";
import { adjacency, emphasisCss, neighbourhood, type ExplorerEdge, type ExplorerGroup, type ExplorerHeader, type ExplorerItem } from "./model";
import "./knowledge.css";
import { useScopedStyleSheet } from "./useScopedStyleSheet";

const PANEL_WIDTH = 400;
/** Explorer width from which details sit beside the map instead of in a sheet. */
const SIDE_PANEL_FROM = 1000;
const edgeTypes = { relation: RelationEdge };

export interface ExplorerDetails {
  title: string;
  caption: string;
  body: ReactNode;
}

export interface GraphExplorerProps {
  /** Accessible name of the map, e.g. "Abu Dhabi governance graph". */
  label: string;
  tone: "governance" | "twin";
  items: ExplorerItem[];
  edges: ExplorerEdge[];
  headers?: ExplorerHeader[];
  groups: ExplorerGroup[];
  nodeTypes: NodeTypes;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  /** Groups a type filter keeps; the rest are dimmed. Null: no filter. */
  keepGroups?: Set<string> | null;
  /** Extra controls in the toolbar (filters). */
  controls?: ReactNode;
  /** A persistent note above the map (privacy, provenance). */
  notice?: ReactNode;
  /** The legend; gets the id prefix of the arrow markers so its samples match the map. */
  legend: (markers: string) => ReactNode;
  details: (item: ExplorerItem, jump: (id: string) => void) => ExplorerDetails;
  searchPlaceholder: string;
  listMeta?: (item: ExplorerItem) => ReactNode;
  minimapColor: (item: ExplorerItem) => string;
  /**
   * On phones, open at a readable zoom on this region (its top or its centre) instead of
   * fitting a map too large to read at phone width. The fit button still shows everything.
   */
  phoneStart?: { rect: Rect; align: "top" | "center" } | null;
  /** Keyboard (Tab) order of the nodes. Defaults to reading order: left to right, top to bottom. */
  tabOrder?: (a: ExplorerItem, b: ExplorerItem) => number;
}

const readingOrder = (a: ExplorerItem, b: ExplorerItem) => a.rect.x - b.rect.x || a.rect.y - b.rect.y;

export function GraphExplorer(props: GraphExplorerProps) {
  useLocale();
  return (
    <ReactFlowProvider>
      <Explorer {...props} />
    </ReactFlowProvider>
  );
}

function Explorer({
  label,
  tone,
  items,
  edges,
  headers = [],
  groups,
  nodeTypes,
  selectedId,
  onSelect,
  keepGroups = null,
  controls,
  notice,
  legend,
  details,
  searchPlaceholder,
  listMeta,
  minimapColor,
  phoneStart = null,
  tabOrder = readingOrder,
}: GraphExplorerProps) {
  const uiLocale = useLocale();
  const flow = useReactFlow();
  const reduceMotion = useReducedMotion();
  const isDesktop = useIsDesktop();
  const scope = useId().replace(/[^a-zA-Z0-9]/g, "");
  const rootRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const { width } = useElementSize(rootRef);
  const wide = width >= SIDE_PANEL_FROM;

  const [view, setView] = useState<"map" | "list">("map");
  const [query, setQuery] = useState("");
  const [legendOpen, setLegendOpen] = useState(false);
  const [hoverNode, setHoverNode] = useState<string | null>(null);
  const [focusNode, setFocusNode] = useState<string | null>(null);
  const [hoverEdge, setHoverEdge] = useState<string | null>(null);
  const [announce, setAnnounce] = useState("");

  const byId = useMemo(() => new Map(items.map((i) => [i.id, i])), [items, uiLocale]);
  const edgeById = useMemo(() => new Map(edges.map((e) => [e.id, e])), [edges, uiLocale]);
  const adj = useMemo(() => adjacency(edges), [edges, uiLocale]);
  const selected = selectedId ? (byId.get(selectedId) ?? null) : null;
  const panelOpen = wide && Boolean(selected);
  const panelOpenRef = useRef(panelOpen);
  panelOpenRef.current = panelOpen;

  const focusId = hoverNode ?? focusNode ?? selected?.id ?? null;
  const hood = useMemo(() => (focusId ? neighbourhood(focusId, adj) : null), [focusId, adj, uiLocale]);
  const css = useMemo(() => emphasisCss(scope, focusId, hood), [scope, focusId, hood, uiLocale]);
  useScopedStyleSheet(css);

  // --- viewport -----------------------------------------------------------------------------------

  const fit = useCallback(() => {
    void flow.fitView({ padding: 0.04, duration: reduceMotion ? 0 : 350 });
  }, [flow, reduceMotion, uiLocale]);

  /** Bring a node into view: centred at a readable zoom, or only nudged if already visible. */
  const reveal = useCallback(
    (id: string, mode: "center" | "ensure", animate = true, initial = false) => {
      const item = byId.get(id);
      const el = canvasRef.current;
      if (!item || !el) return;
      const covered = wide && !panelOpenRef.current ? PANEL_WIDTH : 0;
      const w = el.clientWidth - covered;
      const h = el.clientHeight;
      const viewport = flow.getViewport();
      const cx = item.rect.x + item.rect.width / 2;
      const cy = item.rect.y + item.rect.height / 2;
      if (mode === "ensure") {
        const sx = cx * viewport.zoom + viewport.x;
        const sy = cy * viewport.zoom + viewport.y;
        const mx = (item.rect.width * viewport.zoom) / 2 + 24;
        const my = (item.rect.height * viewport.zoom) / 2 + 24;
        if (sx > mx && sx < w - mx && sy > my && sy < h - my) return;
      }
      // Readable (full labels) but with enough of the neighbourhood around it.
      const readable = isDesktop ? 0.86 : 0.82;
      const zoom = mode === "ensure" ? viewport.zoom : initial ? readable : Math.min(1.2, Math.max(viewport.zoom, readable));
      void flow.setViewport({ x: w / 2 - cx * zoom, y: h / 2 - cy * zoom, zoom }, { duration: animate && !reduceMotion ? 450 : 0 });
    },
    [byId, flow, wide, isDesktop, reduceMotion, uiLocale],
  );

  const lastInternal = useRef<string | null>(selectedId);
  /** Set once someone pans, zooms or selects: from then on the map stays where they put it. */
  const userMoved = useRef(false);
  const select = useCallback(
    (id: string | null, how: "pointer" | "keyboard" | "search" | "jump") => {
      lastInternal.current = id;
      if (id) userMoved.current = true;
      onSelect(id);
      setAnnounce(id ? `Showing details for ${byId.get(id)?.label ?? tr("copy.this_item_973c239")}` : tr("copy.details_closed_3c5383e"));
      if (id && view === "map") reveal(id, how === "search" || how === "jump" ? "center" : "ensure");
    },
    [onSelect, byId, reveal, view, uiLocale],
  );

  // Until someone pans or zooms, keep the map framed: refit when the layout is rebuilt (a new
  // viewport shape) or the canvas is resized (e.g. the assistant docks beside the page).
  const reframe = useCallback(() => {
    const id = lastInternal.current;
    if (id && byId.has(id)) reveal(id, "center", false);
    else void flow.fitView({ padding: 0.04 });
  }, [byId, reveal, flow, uiLocale]);
  const firstItems = useRef(items);
  useEffect(() => {
    if (firstItems.current === items) return;
    firstItems.current = items;
    userMoved.current = false;
    if (view === "map") requestAnimationFrame(reframe);
  }, [items, reframe, view]);
  const [canvasSize, setCanvasSize] = useState({ width: 0, height: 0 });
  const lastSize = useRef(canvasSize);
  useEffect(() => {
    if (view !== "map") return;
    const el = canvasRef.current;
    if (!el) return;
    lastSize.current = { width: 0, height: 0 };
    const update = () => setCanvasSize({ width: el.clientWidth, height: el.clientHeight });
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, [view]);
  useEffect(() => {
    const prev = lastSize.current;
    lastSize.current = canvasSize;
    if (!prev.width || !canvasSize.width || userMoved.current || view !== "map") return;
    const dw = Math.abs(prev.width - canvasSize.width);
    if (dw < 24 && Math.abs(prev.height - canvasSize.height) < 24) return;
    // The details panel opening or closing is not a reason to reframe.
    if (Math.abs(dw - PANEL_WIDTH) < 24) return;
    const timer = window.setTimeout(reframe, 120);
    return () => window.clearTimeout(timer);
  }, [canvasSize, reframe, view]);

  // Selection changed from outside (deep link, back button): bring it into view.
  useEffect(() => {
    if (selectedId === lastInternal.current) return;
    lastInternal.current = selectedId;
    if (selectedId && view === "map") reveal(selectedId, "center");
  }, [selectedId, reveal, view]);

  // What was selected when the map mounted: centre on it instead of fitting the whole map.
  // Kept stable while the map is shown (a changing `fitView` prop would queue another fit).
  const selectedAtMount = useRef(selectedId);
  const startOnRegion = !isDesktop && phoneStart !== null;
  const onInit = useCallback(() => {
    const id = selectedAtMount.current;
    if (id && byId.has(id)) {
      reveal(id, "center", false, true);
    } else if (startOnRegion && phoneStart && canvasRef.current) {
      const zoom = 0.56;
      const { rect, align } = phoneStart;
      const w = canvasRef.current.clientWidth;
      const h = canvasRef.current.clientHeight;
      const y = align === "top" ? 16 - rect.y * zoom : h / 2 - (rect.y + rect.height / 2) * zoom;
      void flow.setViewport({ x: w / 2 - (rect.x + rect.width / 2) * zoom, y, zoom });
    }
  }, [byId, reveal, startOnRegion, phoneStart, flow, uiLocale]);

  // --- nodes and edges ---------------------------------------------------------------------------

  const markers = `kg${scope}`;
  const flowNodes = useMemo(() => {
    const headerNodes: KgHeaderNode[] = headers.map((header) => ({
      id: header.id,
      type: "kgHeader",
      position: { x: header.rect.x, y: header.rect.y },
      width: header.rect.width,
      height: header.rect.height,
      data: { header },
      draggable: false,
      selectable: false,
      focusable: false,
      className: "kg-static",
    }));
    // DOM order is Tab order.
    const nodes: KgFlowNode[] = [...items].sort(tabOrder).map((item) => {
      const isSelected = item.id === selectedId;
      return {
        id: item.id,
        type: item.nodeType,
        position: { x: item.rect.x, y: item.rect.y },
        width: item.rect.width,
        height: item.rect.height,
        data: { item, selected: isSelected },
        draggable: false,
        ariaRole: "button",
        ariaLabel: `${item.typeLabel}: ${item.label}`,
        domAttributes: { "aria-pressed": isSelected },
        className: keepGroups && !keepGroups.has(item.group) ? "kg-out" : undefined,
      };
    });
    return [...headerNodes, ...nodes];
  }, [items, headers, selectedId, keepGroups, tabOrder, uiLocale]);

  const flowEdges = useMemo<KgFlowEdge[]>(
    () =>
      edges.map((edge) => {
        const out = keepGroups && !keepGroups.has(byId.get(edge.source)?.group ?? "") && !keepGroups.has(byId.get(edge.target)?.group ?? "");
        return {
          id: edge.id,
          source: edge.source,
          target: edge.target,
          type: "relation",
          data: { edge, markers },
          focusable: false,
          selectable: false,
          // Relations are read in the details panel and the list view; the lines are decoration.
          domAttributes: { "aria-hidden": true },
          className: out ? "kg-out" : undefined,
        };
      }),
    [edges, keepGroups, byId, markers, uiLocale],
  );

  const bounds = useMemo(() => boundsOf([...items.map((i) => i.rect), ...headers.map((h) => h.rect)]), [items, headers, uiLocale]);
  const allNodeTypes = useMemo(() => ({ ...nodeTypes, kgHeader: HeaderNode }), [nodeTypes, uiLocale]);
  const hovered = hoverEdge ? edgeById.get(hoverEdge) : undefined;
  // The relation label follows the pointer (moved directly, without re-rendering the map).
  const hoverLabelRef = useRef<HTMLDivElement>(null);
  const moveHoverLabel = useCallback((event: ReactMouseEvent) => {
    const label = hoverLabelRef.current;
    const canvas = canvasRef.current;
    if (!label || !canvas) return;
    const box = canvas.getBoundingClientRect();
    label.style.transform = `translate(${event.clientX - box.left}px, ${event.clientY - box.top}px) translate(-50%, calc(-100% - 12px))`;
  }, [uiLocale]);

  // --- keyboard ------------------------------------------------------------------------------------

  useSearchShortcut(useCallback(() => searchRef.current?.focus(), [uiLocale]));

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    const nodeEl = target.closest?.(".react-flow__node");
    if (nodeEl && (event.key === "Enter" || event.key === " ")) {
      const id = nodeEl.getAttribute("data-id");
      if (id && byId.has(id)) {
        event.preventDefault();
        select(id, "keyboard");
      }
      return;
    }
    if (event.key === "Escape" && selectedId) {
      event.preventDefault();
      const id = selectedId;
      select(null, "keyboard");
      requestAnimationFrame(() => {
        const el = canvasRef.current?.querySelector<HTMLElement>(`.react-flow__node[data-id="${CSS.escape(id)}"]`);
        if (el && (target.closest(".kg-details") || target === document.body || nodeEl)) el.focus({ preventScroll: true });
      });
    }
  };

  const detail = selected ? details(selected, (id) => select(id, "jump")) : null;
  const legendId = `${scope}-legend`;

  return (
    <div
      ref={rootRef}
      className="flex min-h-0 flex-1 flex-col"
      onKeyDown={onKeyDown}
      onFocus={(event) => {
        // Keyboard focus lights up a node's neighbourhood like hovering does (not mouse focus).
        const target = event.target as HTMLElement;
        const id = target.matches?.(".react-flow__node:focus-visible") ? target.getAttribute("data-id") : null;
        setFocusNode(id && byId.has(id) ? id : null);
      }}
      onBlur={() => setFocusNode(null)}
    >
      <Markers id={markers} />
      <p className="sr-only" aria-live="polite">
        {localize(announce)}
      </p>

      <div className="flex flex-wrap items-center gap-x-2 gap-y-2.5 border-b border-line px-4 py-3 sm:px-6 @4xl/main:flex-nowrap @4xl/main:gap-3 lg:px-8">
        <div className="order-1 min-w-0 flex-1 @4xl/main:flex-none">
          <GraphSearch
            items={items}
            query={query}
            onQueryChange={setQuery}
            onChoose={(item) => select(item.id, "search")}
            suggest={view === "map"}
            placeholder={localize(searchPlaceholder)}
            inputRef={searchRef}
          />
        </div>
        {view === "map" && (
          <button
            type="button"
            aria-expanded={legendOpen}
            aria-controls={legendId}
            onClick={() => setLegendOpen((o) => !o)}
            title={tr("copy.legend_5846955")}
            className={cn(
              "order-2 inline-flex size-10 shrink-0 items-center justify-center gap-1.5 rounded-md text-sm font-medium transition-colors hover:bg-sunken hover:text-ink @4xl/main:order-4 @4xl/main:h-9 @4xl/main:w-auto @4xl/main:px-3",
              legendOpen ? "bg-sunken text-ink @4xl/main:bg-transparent" : "text-muted",
            )}
          >
            <Info className="size-4" aria-hidden />
            <span className="sr-only @4xl/main:not-sr-only">{tr("copy.legend_5846955")}</span>
          </button>
        )}
        {controls && <div className="order-4 w-full min-w-0 @4xl/main:order-2 @4xl/main:w-auto @4xl/main:flex-1">{localize(controls)}</div>}
        <Segmented
          label={tr("copy.view_69bd4ef")}
          size="sm"
          className="order-3 shrink-0 @4xl/main:ms-auto"
          value={view}
          onChange={(v) => {
            selectedAtMount.current = selectedId;
            setView(v);
            setHoverEdge(null);
            setHoverNode(null);
          }}
          options={[
            { value: "map", label: <span className="sr-only @md/main:not-sr-only">{tr("common.ab478f3efc")}</span>, icon: <Network className="size-3.5" aria-hidden /> },
            { value: "list", label: <span className="sr-only @md/main:not-sr-only">{tr("common.a1fffaaafb")}</span>, icon: <List className="size-3.5" aria-hidden /> },
          ]}
        />
      </div>

      {legendOpen && view === "map" && (
        <div id={legendId} className="kg-legend border-b border-line bg-surface px-4 py-2.5 sm:px-6 lg:px-8">
          {localize(legend(markers))}
        </div>
      )}
      {localize(notice)}

      <div className="flex min-h-0 flex-1">
        <div className="relative min-w-0 flex-1">
          {view === "map" ? (
            <div className="relative h-[58dvh] min-h-[340px] lg:h-full lg:min-h-0">
              <div
                ref={canvasRef}
                className={cn("kg-canvas adapt-flow absolute inset-0", tone === "governance" ? "canvas-dots bg-canvas" : "bg-muted-surface")}
                dir="ltr"
                data-kg={scope}
                data-tone={tone}
                data-focus={focusId ? "" : undefined}
              >
                <ReactFlow<KgFlowNode | KgHeaderNode, KgFlowEdge>
                  aria-label={localize(label)}
                  nodes={flowNodes}
                  edges={flowEdges}
                  nodeTypes={allNodeTypes}
                  edgeTypes={edgeTypes}
                  onInit={onInit}
                  onMoveStart={(event) => {
                    if (event) userMoved.current = true;
                  }}
                  fitView={!selectedAtMount.current && !startOnRegion}
                  fitViewOptions={{ padding: 0.04 }}
                  minZoom={0.08}
                  maxZoom={2}
                  nodesDraggable={false}
                  nodesConnectable={false}
                  elementsSelectable={false}
                  edgesFocusable={false}
                  zoomOnDoubleClick={false}
                  panOnDrag
                  zoomOnPinch
                  onNodeClick={(_, node) => byId.has(node.id) && select(node.id, "pointer")}
                  onNodeMouseEnter={(_, node) => byId.has(node.id) && setHoverNode(node.id)}
                  onNodeMouseLeave={() => setHoverNode(null)}
                  onEdgeMouseEnter={(event, edge) => {
                    setHoverEdge(edge.id);
                    moveHoverLabel(event);
                  }}
                  onEdgeMouseMove={moveHoverLabel}
                  onEdgeMouseLeave={() => setHoverEdge(null)}
                  onPaneClick={() => selectedId && select(null, "pointer")}
                  attributionPosition="top-right"
                  ariaLabelConfig={graphA11y()}
                >
                  <ZoomSync target={canvasRef} />
                  <Panel position="bottom-left">
                    <ZoomControls onFit={fit} />
                  </Panel>
                  <Panel position="top-left" className="pointer-events-none"><span className="rounded-full border border-line bg-surface/95 px-3 py-1.5 text-2xs text-muted shadow-card">{isDesktop ? tr("copy.drag_to_explore_select_a_node_for_details_06d7ff3") : tr("copy.drag_to_explore_pinch_to_zoom_70c4d68")}</span></Panel>
                  {isDesktop && wide && (
                    <ZoomedInOnly bounds={bounds}>
                      <MiniMap
                        position="bottom-left"
                        style={{ marginLeft: 60, width: 176, height: 110 }}
                        pannable
                        zoomable
                        nodeBorderRadius={2}
                        nodeColor={(node) => {
                          const item = byId.get(node.id);
                          return item ? minimapColor(item) : "transparent";
                        }}
                      />
                    </ZoomedInOnly>
                  )}
                </ReactFlow>
                <div ref={hoverLabelRef} className="kg-hover-label" hidden={!hovered} aria-hidden>
                  {localize(hovered?.text)}
                </div>
              </div>
            </div>
          ) : (
            <GraphList items={items} groups={groups} query={query} keepGroups={keepGroups} selectedId={selectedId} onSelect={(id) => select(id, "pointer")} renderMeta={listMeta} />
          )}
        </div>

        <AnimatePresence initial={false}>
          {panelOpen && detail && selected && (
            <motion.aside
              key="details"
              aria-label={localize(tr("copy.details_v0_0454e42", { v0: detail.title }))}
              initial={reduceMotion ? false : { width: 0 }}
              animate={{ width: PANEL_WIDTH }}
              exit={reduceMotion ? { width: 0, transition: { duration: 0 } } : { width: 0 }}
              transition={{ duration: 0.28, ease: [0.2, 0, 0, 1] }}
              className="kg-details relative shrink-0 overflow-hidden border-s border-line bg-surface"
            >
              <div className="flex h-full flex-col" style={{ width: PANEL_WIDTH }}>
                <div className="flex items-start gap-3 border-b border-line px-5 py-4">
                  <div className="min-w-0 flex-1">
                    <p className="text-xs text-muted">{localize(detail.caption)}</p>
                    <h2 className="mt-0.5 text-lg leading-snug">{localize(detail.title)}</h2>
                  </div>
                  <IconButton label={tr("copy.close_details_433da6d")} size="sm" onClick={() => select(null, "pointer")}>
                    <X className="size-5" aria-hidden />
                  </IconButton>
                </div>
                <motion.div
                  key={selected.id}
                  initial={reduceMotion ? false : { opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ duration: 0.18 }}
                  className="min-h-0 flex-1 overflow-y-auto px-5 pt-4 pb-28"
                >
                  {localize(detail.body)}
                </motion.div>
              </div>
            </motion.aside>
          )}
        </AnimatePresence>
      </div>

      {!wide && (
        <Sheet open={Boolean(selected && detail)} onClose={() => select(null, "pointer")} title={localize(detail?.title ?? "")} description={localize(detail?.caption)}>
          <div className="kg-details">{localize(detail?.body)}</div>
        </Sheet>
      )}
    </div>
  );
}
