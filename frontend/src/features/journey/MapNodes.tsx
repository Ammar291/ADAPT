import { tr, localize, useLocale } from "@/i18n";
/**
 * Custom React Flow nodes for the transit map: "stations" for tasks, appointments and
 * completed steps, and compact "satellite" pills for documents, requirements, outside events
 * and approvals.
 */
import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { CalendarClock, Waypoints } from "lucide-react";
import type { CSSProperties } from "react";
import type { JourneyNode } from "@/domain/journey";
import { laneColor } from "@/components/ui/AreaLabel";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { cn } from "@/lib/cn";
import { daysUntil, dueLabel } from "@/lib/format";
import type { NodeEmphasis } from "./graph";
import { KIND_ICON, KIND_LABEL, PILL_FRAME, STATION_FRAME, StatusGlyph } from "./visuals";

export type MapNodeData = {
  node: JourneyNode;
  emphasis: NodeEmphasis;
  critical: boolean;
};

export type StationFlowNode = Node<MapNodeData, "station">;
export type SatelliteFlowNode = Node<MapNodeData, "satellite">;
export type MapFlowNode = StationFlowNode | SatelliteFlowNode;

const HIDDEN_HANDLE: CSSProperties = { opacity: 0, pointerEvents: "none", width: 1, height: 1, minWidth: 0, minHeight: 0, border: 0 };

function Handles({ vertical }: { vertical: "station" | "satellite" }) {
  useLocale();
  return (
    <>
      <Handle type="target" id="in" position={Position.Left} isConnectable={false} style={HIDDEN_HANDLE} />
      <Handle type="source" id="out" position={Position.Right} isConnectable={false} style={HIDDEN_HANDLE} />
      <Handle type="target" id="down" position={Position.Bottom} isConnectable={false} style={HIDDEN_HANDLE} />
      {vertical === "satellite" && <Handle type="source" id="up" position={Position.Top} isConnectable={false} style={HIDDEN_HANDLE} />}
    </>
  );
}

const EMPHASIS: Record<NodeEmphasis, string> = {
  normal: "",
  dimmed: "opacity-25 saturate-50",
  related: "shadow-raised",
  focused: "shadow-overlay outline-2 outline-offset-[3px] outline-ink",
};

export function dueText(node: JourneyNode): { text: string; short: string; overdue: boolean } | null {
  if (!node.dueBy || node.status === "done" || node.status === "not_applicable") return null;
  const days = daysUntil(node.dueBy);
  return { text: tr("copy.due_v0_b3f85fc", { v0: dueLabel(node.dueBy) }), short: dueLabel(node.dueBy), overdue: days !== null && days < 0 };
}

export function StationNode({ data }: NodeProps<StationFlowNode>) {
  useLocale();
  const { node, emphasis, critical } = data;
  const Icon = KIND_ICON[node.kind];
  const due = dueText(node);
  const done = node.status === "done";

  return (
    <div
      className={cn(
        "relative flex h-full w-full cursor-pointer overflow-hidden rounded-lg text-start transition-[opacity,box-shadow,filter] duration-200 hover:shadow-raised",
        STATION_FRAME[node.status],
        EMPHASIS[emphasis],
      )}
    >
      <span className="absolute inset-y-0 start-0 w-[3px]" style={{ background: laneColor(node.area) }} aria-hidden />
      {done ? (
        <div className="flex min-w-0 flex-1 items-center gap-2.5 ps-3.5 pe-3">
          <StatusGlyph status="done" />
          <p className="line-clamp-2 min-w-0 text-xs leading-4 font-medium text-muted">{localize(node.title)}</p>
        </div>
      ) : (
        <div className="flex min-w-0 flex-1 flex-col justify-between gap-1 py-2 ps-4 pe-3">
          <div className="flex items-center gap-1.5 text-2xs text-muted">
            <Icon className="size-3.5 shrink-0" aria-hidden />
            <span className="truncate">{localize(KIND_LABEL[node.kind])}</span>
            {critical && (
              <span className="ms-auto inline-flex shrink-0 items-center gap-1 font-medium text-primary-strong">
                <Waypoints className="size-3.5" aria-hidden />
                {tr("copy.critical_path_c77e227")}</span>
            )}
          </div>
          <p className="line-clamp-2 text-sm leading-5 font-medium text-ink">{localize(node.title)}</p>
          <div className="flex items-center justify-between gap-2">
            <StatusBadge status={node.status} />
            {due && (
              <span className={cn("tabular inline-flex min-w-0 items-center gap-1 text-2xs", due.overdue ? "font-medium text-danger" : "text-subtle")}>
                <CalendarClock className="size-3 shrink-0" aria-hidden />
                <span className="truncate">{localize(due.short)}</span>
              </span>
            )}
          </div>
        </div>
      )}
      <Handles vertical="station" />
    </div>
  );
}

export function SatelliteNode({ data }: NodeProps<SatelliteFlowNode>) {
  useLocale();
  const { node, emphasis } = data;
  const Icon = KIND_ICON[node.kind];
  return (
    <div
      className={cn(
        "relative flex h-full w-full cursor-pointer items-center gap-2 rounded-full ps-3 pe-1.5 text-start transition-[opacity,box-shadow,filter] duration-200 hover:shadow-raised",
        PILL_FRAME[node.status],
        EMPHASIS[emphasis],
      )}
    >
      <Icon className="size-4 shrink-0" style={{ color: laneColor(node.area) }} aria-hidden />
      <span className={cn("line-clamp-2 min-w-0 flex-1 text-2xs leading-[14px] font-medium", node.status === "done" ? "text-muted" : "text-ink")}>{localize(node.title)}</span>
      <StatusGlyph status={node.status} />
      <Handles vertical="satellite" />
    </div>
  );
}

export const nodeTypes = { station: StationNode, satellite: SatelliteNode };
