import { localize, useLocale } from "@/i18n";
/**
 * The dependency edge of the transit map. Its route is precomputed by `routeEdges` (orthogonal,
 * never behind a step it doesn't connect); this only draws it in the right style.
 */
import { BaseEdge, EdgeLabelRenderer, getSmoothStepPath, type Edge, type EdgeProps } from "@xyflow/react";
import type { EdgeVisual } from "./graph";
import type { Point } from "./routing";
import { EDGE_COLOR, EDGE_OPACITY } from "./visuals";

export type TransitEdgeData = {
  visual: EdgeVisual;
  /** SVG path in flow coordinates. */
  path: string | null;
  label: Point | null;
};

export type TransitFlowEdge = Edge<TransitEdgeData, "transit">;

export function TransitEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, markerEnd }: EdgeProps<TransitFlowEdge>) {
  useLocale();
  const visual = data?.visual;
  const path = data?.path ?? getSmoothStepPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, borderRadius: 12 })[0];
  if (!visual) return <BaseEdge id={id} path={path} markerEnd={markerEnd} />;

  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        markerEnd={markerEnd}
        interactionWidth={0}
        style={{
          stroke: EDGE_COLOR[visual.tone],
          strokeWidth: visual.width,
          strokeDasharray: visual.dash,
          strokeLinecap: visual.dash?.startsWith("0.5") ? "round" : undefined,
          opacity: visual.dimmed ? 0.08 : EDGE_OPACITY[visual.tone],
        }}
      />
      {visual.label && data?.label && !visual.dimmed && (
        <EdgeLabelRenderer>
          <span
            className="pointer-events-none absolute rounded-full border border-line-strong bg-surface px-1.5 text-2xs leading-4 text-muted"
            style={{ transform: `translate(-50%, -50%) translate(${data.label.x}px, ${data.label.y}px)` }}
          >
            {localize(visual.label)}
          </span>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

export const edgeTypes = { transit: TransitEdge };
