import { tr, localize, useLocale } from "@/i18n";
/**
 * React Flow pieces shared by both explorers: node/edge types, the relation edge, column
 * headings, arrow markers, zoom sync and the zoom controls.
 */
import { EdgeLabelRenderer, Handle, Position, useReactFlow, useStore, type Edge, type EdgeProps, type Node, type NodeProps } from "@xyflow/react";
import { Maximize, Minus, Plus } from "lucide-react";
import { useLayoutEffect, type ReactNode, type RefObject } from "react";
import { cn } from "@/lib/cn";
import type { Rect } from "../layout/geometry";
import type { ExplorerEdge, ExplorerHeader, ExplorerItem } from "./model";

export type KgNodeData = { item: ExplorerItem; selected: boolean };
export type KgFlowNode = Node<KgNodeData>;
export type KgHeaderData = { header: ExplorerHeader };
export type KgHeaderNode = Node<KgHeaderData, "kgHeader">;
export type KgEdgeData = { edge: ExplorerEdge; markers: string };
export type KgFlowEdge = Edge<KgEdgeData, "relation">;

/** Invisible anchors: edges are routed by the layout, but React Flow needs a handle to draw them. */
export function Anchors() {
  useLocale();
  return (
    <>
      <Handle type="target" position={Position.Left} className="kg-handle" isConnectable={false} />
      <Handle type="source" position={Position.Right} className="kg-handle" isConnectable={false} />
    </>
  );
}

export function RelationEdge({ data }: EdgeProps<KgFlowEdge>) {
  useLocale();
  if (!data) return null;
  const { edge, markers } = data;
  return (
    <>
      <path d={edge.path} className={cn("kg-edge", `kg-e-${edge.variant}`)} markerEnd={edge.marker ? `url(#${markers}-${edge.marker})` : undefined} />
      <path d={edge.path} className="kg-edge-hit" />
      {edge.pinnedLabel && (
        <EdgeLabelRenderer>
          <div
            className="kg-pin nodrag nopan"
            data-variant={edge.variant}
            style={{ transform: `translate(-50%, -50%) translate(${edge.labelPoint.x}px, ${edge.labelPoint.y}px)` }}
          >
            {localize(edge.pinnedLabel)}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

export function HeaderNode({ data }: NodeProps<KgHeaderNode>) {
  useLocale();
  const { header } = data;
  return (
    <div className="flex h-full w-full flex-col justify-end" aria-hidden>
      <div className="flex min-w-0 items-baseline gap-2 pb-2">
        <span className="kg-header-title min-w-0 font-display font-medium text-ink">{localize(header.title)}</span>
        <span className="kg-header-count tabular shrink-0 text-subtle">{localize(header.count)}</span>
      </div>
      <div className="kg-header-rule w-full bg-line-strong" />
    </div>
  );
}

/** Arrowheads that scale with the (counter-scaled) stroke, coloured by token. */
export function Markers({ id }: { id: string }) {
  useLocale();
  return (
    <svg width="0" height="0" className="absolute" aria-hidden focusable="false">
      <defs>
        {(["ink", "danger"] as const).map((tone) => (
          <marker
            key={tone}
            id={`${id}-${tone}`}
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="5.5"
            markerHeight="5.5"
            markerUnits="strokeWidth"
            orient="auto-start-reverse"
          >
            <path d="M0,0.5 L10,5 L0,9.5 z" className={`kg-marker-${tone}`} />
          </marker>
        ))}
      </defs>
    </svg>
  );
}

export type Lod = "far" | "compact" | "overview" | "detail";

/** How much text nodes show at a zoom level (labels never render below ~10.5px). */
export function lodFor(zoom: number): Lod {
  if (zoom < 0.3) return "far";
  if (zoom < 0.46) return "compact";
  if (zoom < 0.8) return "overview";
  return "detail";
}

/** Mirrors the zoom into `--kz` and `data-lod` on the canvas, without re-rendering nodes. */
export function ZoomSync({ target }: { target: RefObject<HTMLElement | null> }) {
  const zoom = useStore((s) => s.transform[2]);
  useLayoutEffect(() => {
    const apply = () => {
      const el = target.current;
      if (!el) return false;
      el.style.setProperty("--kz", zoom.toFixed(4));
      const lod = lodFor(zoom);
      if (el.dataset.lod !== lod) el.dataset.lod = lod;
      return true;
    };
    // On the first commit the canvas ref may not be attached yet (child effects run first).
    if (!apply()) {
      const frame = requestAnimationFrame(apply);
      return () => cancelAnimationFrame(frame);
    }
  }, [zoom, target]);
  return null;
}

const controlButton =
  "inline-flex size-11 items-center justify-center text-ink transition-colors hover:bg-sunken focus-visible:relative focus-visible:z-10 lg:size-9";

export function ZoomControls({ onFit }: { onFit: () => void }) {
  useLocale();
  const flow = useReactFlow();
  return (
    <div role="group" aria-label={tr("copy.zoom_9b3cbed")} className="flex flex-col overflow-hidden rounded-md border border-line bg-surface shadow-card">
      <button type="button" className={controlButton} onClick={() => void flow.zoomIn({ duration: 200 })} aria-label={tr("copy.zoom_in_4fc05f2")} title={tr("copy.zoom_in_4fc05f2")}>
        <Plus className="size-4" aria-hidden />
      </button>
      <button type="button" className={cn(controlButton, "border-y border-line")} onClick={() => void flow.zoomOut({ duration: 200 })} aria-label={tr("copy.zoom_out_a4ae4b2")} title={tr("copy.zoom_out_a4ae4b2")}>
        <Minus className="size-4" aria-hidden />
      </button>
      <button type="button" className={controlButton} onClick={onFit} aria-label={tr("copy.fit_the_whole_map_a881f82")} title={tr("copy.fit_the_whole_map_a881f82")}>
        <Maximize className="size-4" aria-hidden />
      </button>
    </div>
  );
}

/**
 * Renders its children only once the map is zoomed in well past "fit": at fit view the whole
 * map is on screen and an overview map would only cover part of it.
 */
export function ZoomedInOnly({ bounds, children }: { bounds: Rect; children: ReactNode }) {
  useLocale();
  const show = useStore((s) => {
    if (!bounds.width || !bounds.height || !s.width || !s.height) return false;
    const fit = Math.min(s.width / (bounds.width * 1.08), s.height / (bounds.height * 1.08));
    return s.transform[2] > fit * 1.35;
  });
  return show ? <>{localize(children)}</> : null;
}
