import { graphA11y } from "@/i18n/graphA11y";
import { tr, localize, useLocale } from "@/i18n";
import {
  Controls,
  EdgeLabelRenderer,
  getBezierPath,
  Handle,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useNodesInitialized,
  useReactFlow,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeHandle,
  type NodeProps,
} from "@xyflow/react";
import { Check, Clock, LocateFixed, Undo2, Wrench } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { memo, useEffect, useMemo, useRef, useState } from "react";
import type { AgentStage, AgentWorkflow } from "@/domain/runs";
import type { RunView, StageStatus, StageView } from "@/lib/events/runEvents";
import { cn } from "@/lib/cn";
import { formatDuration } from "@/lib/format";
import { conditionLabel, edgeState, stageLine, takenBranches, type EdgeState } from "./flow";
import { chooseOrientation, fitZoom, LAYOUT_SIZES, layoutWorkflow, type Orientation } from "./layout";
import { KindIcon, STAGE_STATUS, StagePill } from "./StageStatus";

// --- nodes ------------------------------------------------------------------------------------------

interface StageNodeData extends Record<string, unknown> {
  stage: AgentStage;
  view: StageView | undefined;
  status: StageStatus;
  selected: boolean;
  orientation: Orientation;
  animate: boolean;
  runStatus: RunView["status"];
}

type StageFlowNode = Node<StageNodeData, "stage">;

const HIDDEN_HANDLE = { opacity: 0, pointerEvents: "none" as const, width: 1, height: 1, minWidth: 0, minHeight: 0, border: 0 };

/** Thin progress line at the foot of a running stage: determinate when known, else a calm sweep. */
function StageProgress({ progress, animate }: { progress: number | null; animate: boolean }) {
  useLocale();
  return (
    <span className="absolute inset-x-3 bottom-1.5 h-[3px] overflow-hidden rounded-full bg-primary-tint" aria-hidden>
      {progress !== null ? (
        <span className="block h-full rounded-full bg-primary transition-[width] duration-500 ease-out" style={{ width: `${Math.round(progress * 100)}%` }} />
      ) : animate ? (
        <motion.span
          className="absolute inset-y-0 w-1/3 rounded-full bg-primary/70"
          initial={{ left: "-33%" }}
          animate={{ left: "100%" }}
          transition={{ duration: 1.8, repeat: Infinity, ease: [0.4, 0, 0.2, 1] }}
        />
      ) : (
        <span className="block h-full w-1/3 rounded-full bg-primary/70" />
      )}
    </span>
  );
}

function Meta({ view }: { view: StageView | undefined }) {
  useLocale();
  if (!view) return null;
  const tools = view.tools.length;
  return (
    <span className="flex shrink-0 items-center gap-2 text-2xs text-subtle">
      {!!view.durationMs && (
        <span className="tabular inline-flex items-center gap-0.5">
          <Clock className="size-3" aria-hidden />
          {localize(formatDuration(view.durationMs))}
        </span>
      )}
      {tools > 0 && (
        <span className="tabular inline-flex items-center gap-0.5" title={localize(tr("copy.v0_tool_v1_7d79624", { v0: tools, v1: tools === 1 ? "call" : "calls" }))}>
          <Wrench className="size-3" aria-hidden />
          {localize(tools)}
          <span className="sr-only">{tools === 1 ? tr("copy.tool_call_98edbf6") : tr("copy.tool_calls_cc8b5f4")}</span>
        </span>
      )}
    </span>
  );
}

function stageHandles(orientation: "vertical" | "horizontal"): NodeHandle[] {
  const { nodeWidth: w, nodeHeight: h } = LAYOUT_SIZES[orientation];
  const at = (id: string, type: "source" | "target", position: Position, x: number, y: number): NodeHandle => ({ id, type, position, x: x - 0.5, y: y - 0.5, width: 1, height: 1 });
  return orientation === "vertical"
    ? [
        at("in", "target", Position.Top, w / 2, 0),
        at("out", "source", Position.Bottom, w / 2, h),
        at("side-out", "source", Position.Right, w, h / 2),
        at("side-in", "target", Position.Right, w, h / 2),
      ]
    : [
        at("in", "target", Position.Left, 0, h / 2),
        at("out", "source", Position.Right, w, h / 2),
        at("side-out", "source", Position.Bottom, w / 2, h),
        at("side-in", "target", Position.Bottom, w / 2, h),
      ];
}

const StageNode = memo(function StageNode({ data }: NodeProps<StageFlowNode>) {
  useLocale();
  const { stage, view, status, selected, orientation, animate, runStatus } = data;
  const reduce = useReducedMotion();
  const vertical = orientation === "vertical";
  const { nodeWidth, nodeHeight } = LAYOUT_SIZES[orientation];
  const line = stageLine(status, view, stage.description, runStatus);
  const meta = STAGE_STATUS[status];
  const pulse = status === "running" && !reduce;

  return (
    <div className="relative" style={{ width: nodeWidth, height: nodeHeight }}>
      <Handle type="target" id="in" position={vertical ? Position.Top : Position.Left} isConnectable={false} style={HIDDEN_HANDLE} />
      <Handle type="source" id="out" position={vertical ? Position.Bottom : Position.Right} isConnectable={false} style={HIDDEN_HANDLE} />
      <Handle type="source" id="side-out" position={vertical ? Position.Right : Position.Bottom} isConnectable={false} style={HIDDEN_HANDLE} />
      <Handle type="target" id="side-in" position={vertical ? Position.Right : Position.Bottom} isConnectable={false} style={HIDDEN_HANDLE} />
      {pulse && (
        <motion.span
          aria-hidden
          className="pointer-events-none absolute -inset-[5px] rounded-[16px] border-2 border-primary"
          animate={{ opacity: [0.12, 0.45, 0.12] }}
          transition={{ duration: 2.6, repeat: Infinity, ease: "easeInOut" }}
        />
      )}
      {status === "awaiting" && <span aria-hidden className="pointer-events-none absolute -inset-[5px] rounded-[16px] border-2 border-ink/25" />}
      {/* Clicks (and Enter/Space, which click the button) bubble to React Flow's onNodeClick. */}
      <button
        type="button"
        aria-pressed={selected}
        aria-label={localize(`${stage.label}: ${meta.label}. ${line}`)}
        data-stage={stage.id}
        className={cn(
          "nodrag relative flex size-full rounded-xl border text-start transition-[border-color,box-shadow,background-color] duration-300 hover:border-ink/50",
          meta.card,
          vertical ? "items-center gap-3 px-3" : "flex-col justify-between px-3 pt-2.5 pb-3",
          selected && "ring-2 ring-ink ring-offset-2 ring-offset-canvas",
        )}
      >
        {vertical ? (
          <>
            <KindIcon kind={stage.kind} />
            <span className="flex min-w-0 flex-1 flex-col gap-0.5">
              <span className="flex items-center gap-2">
                <span className="min-w-0 flex-1 truncate text-sm font-medium text-ink">{localize(stage.label)}</span>
                <StagePill status={status} animate={animate} />
              </span>
              <span className="flex items-center gap-2">
                <span className={cn("min-w-0 flex-1 truncate text-2xs", status === "failed" ? "text-danger" : "text-muted")}>{localize(line)}</span>
                <Meta view={view} />
              </span>
            </span>
          </>
        ) : (
          <>
            <span className="flex w-full items-center justify-between gap-2">
              <KindIcon kind={stage.kind} className="size-6" />
              <StagePill status={status} animate={animate} />
            </span>
            <span className="w-full truncate text-sm font-medium text-ink">{localize(stage.label)}</span>
            <span className="flex w-full items-center gap-2">
              <span className={cn("min-w-0 flex-1 truncate text-2xs", status === "failed" ? "text-danger" : "text-muted")}>{localize(line)}</span>
              <Meta view={view} />
            </span>
          </>
        )}
        {status === "running" && <StageProgress progress={view?.progress ?? null} animate={animate && !reduce} />}
      </button>
    </div>
  );
});

// --- edges ------------------------------------------------------------------------------------------

interface StageEdgeData extends Record<string, unknown> {
  state: EdgeState;
  condition: string | null;
  skip: boolean;
  orientation: Orientation;
  animate: boolean;
}

type StageFlowEdge = Edge<StageEdgeData, "stage">;

const SKIP_BULGE = 48;
const FIT_OPTIONS = { padding: 0.06, maxZoom: 1 };

const StageEdge = memo(function StageEdge({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data }: EdgeProps<StageFlowEdge>) {
  useLocale();
  const reduce = useReducedMotion();
  const { state, condition, skip, orientation, animate } = data!;
  const vertical = orientation === "vertical";
  let path: string;
  let labelX: number;
  let labelY: number;
  if (skip) {
    const b = SKIP_BULGE;
    path = vertical
      ? `M ${sourceX} ${sourceY} C ${sourceX + b} ${sourceY}, ${targetX + b} ${targetY}, ${targetX} ${targetY}`
      : `M ${sourceX} ${sourceY} C ${sourceX} ${sourceY + b}, ${targetX} ${targetY + b}, ${targetX} ${targetY}`;
    labelX = vertical ? sourceX + b * 0.75 : (sourceX + targetX) / 2;
    labelY = vertical ? (sourceY + targetY) / 2 : sourceY + b * 0.75;
  } else {
    [path, labelX, labelY] = getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition });
  }

  const travelled = state === "done" || state === "active";
  const motionOk = animate && !reduce;
  const labelTransform = skip
    ? vertical
      ? `translate(6px, -50%) translate(${labelX}px, ${labelY}px)`
      : `translate(-50%, 6px) translate(${labelX}px, ${labelY}px)`
    : vertical
      ? `translate(8px, -50%) translate(${labelX}px, ${labelY}px)`
      : `translate(-50%, calc(-100% - 4px)) translate(${labelX}px, ${labelY}px)`;

  return (
    <>
      <path
        d={path}
        fill="none"
        stroke="var(--line-strong)"
        strokeWidth={1.5}
        strokeDasharray={condition || state === "skipped" ? "4 4" : undefined}
        opacity={state === "skipped" ? 0.7 : 1}
      />
      {travelled && (
        <motion.path
          d={path}
          fill="none"
          stroke="var(--teal)"
          strokeWidth={2}
          strokeLinecap="round"
          initial={motionOk ? { pathLength: 0 } : false}
          animate={{ pathLength: state === "done" ? 1 : 0.5 }}
          transition={{ duration: motionOk ? 0.6 : 0, ease: [0.2, 0, 0, 1] }}
        />
      )}
      {state === "active" && motionOk && (
        <motion.path
          d={path}
          fill="none"
          stroke="var(--teal)"
          strokeWidth={2}
          strokeDasharray="3 9"
          strokeLinecap="round"
          animate={{ strokeDashoffset: [0, -24] }}
          transition={{ duration: 1.1, repeat: Infinity, ease: "linear" }}
        />
      )}
      {condition && (
        <EdgeLabelRenderer>
          <div
            className={cn(
              "nodrag nopan pointer-events-none absolute inline-flex items-center gap-1 rounded-full border bg-surface px-2 py-0.5 text-2xs whitespace-nowrap",
              state === "done" || state === "active" ? "border-primary/50 font-medium text-primary-strong" : "border-line text-muted",
              state === "skipped" && "text-subtle",
            )}
            style={{ transform: labelTransform }}
          >
            {condition === "rejected" ? <Undo2 className="size-3" aria-hidden /> : <Check className="size-3" aria-hidden />}
            {localize(conditionLabel(condition))}
            {state === "skipped" && <span className="sr-only">{tr("copy.not_taken_241afd9")}</span>}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
});

const nodeTypes = { stage: StageNode };
const edgeTypes = { stage: StageEdge };

// --- camera -----------------------------------------------------------------------------------------

/** Fits the whole workflow when it is readable; otherwise keeps the live stage in view. */
function Camera({ layoutKey, fits, focusId, follow }: { layoutKey: string; fits: boolean; focusId: string | null; follow: boolean }) {
  const flow = useReactFlow();
  const ready = useNodesInitialized();
  const reduce = useReducedMotion();
  const target = fits || !follow ? null : focusId;
  useEffect(() => {
    if (!ready) return;
    if (fits) {
      void flow.fitView({ ...FIT_OPTIONS, duration: reduce ? 0 : 250 });
      return;
    }
    if (!target) return;
    const node = flow.getInternalNode(target);
    if (!node) return;
    const { width = 0, height = 0 } = node.measured;
    void flow.setCenter(node.internals.positionAbsolute.x + width / 2, node.internals.positionAbsolute.y + height / 2, {
      zoom: 0.9,
      duration: reduce ? 0 : 500,
    });
  }, [ready, layoutKey, fits, target, flow, reduce]);
  return null;
}

function useBox<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [box, setBox] = useState({ width: 0, height: 0 });
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => {
      if (!entry) return;
      // Round so tiny layout shifts don't re-fit the view.
      const width = Math.round(entry.contentRect.width / 24) * 24;
      const height = Math.round(entry.contentRect.height / 24) * 24;
      setBox((prev) => (prev.width === width && prev.height === height ? prev : { width, height }));
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return [ref, box] as const;
}

// --- graph ------------------------------------------------------------------------------------------

export interface WorkflowGraphProps {
  workflow: AgentWorkflow;
  view: RunView;
  statuses: Record<string, StageStatus>;
  selectedId: string | null;
  focusId: string | null;
  onSelect: (id: string) => void;
  /** False while history replays, so a finished run doesn't animate everything at once. */
  animate: boolean;
  className?: string;
}

function Graph({ workflow, view, statuses, selectedId, focusId, onSelect, animate, className }: WorkflowGraphProps) {
  const uiLocale = useLocale();
  const [ref, box] = useBox<HTMLDivElement>();
  const [follow, setFollow] = useState(true);
  const orientation = useMemo(() => (box.width ? chooseOrientation(workflow, box) : "vertical"), [workflow, box, uiLocale]);
  const layout = useMemo(() => layoutWorkflow(workflow, orientation), [workflow, orientation, uiLocale]);
  const fits = box.width > 0 && fitZoom(layout, box, 24) >= 0.7;
  const taken = useMemo(() => takenBranches(workflow, view, statuses), [workflow, view, statuses, uiLocale]);
  const stageById = useMemo(() => new Map(workflow.stages.map((s) => [s.id, s])), [workflow, uiLocale]);

  const nodes: StageFlowNode[] = useMemo(
    () =>
      layout.stages.map((placed) => ({
        id: placed.id,
        type: "stage",
        position: { x: placed.x, y: placed.y },
        // Known size and handle positions: nodes render and connect even if the run's events
        // change them before React Flow measures the DOM (e.g. arriving mid-stream).
        width: LAYOUT_SIZES[orientation].nodeWidth,
        height: LAYOUT_SIZES[orientation].nodeHeight,
        handles: stageHandles(orientation),
        data: {
          stage: stageById.get(placed.id)!,
          view: view.stages[placed.id],
          status: statuses[placed.id] ?? "queued",
          selected: selectedId === placed.id,
          orientation,
          animate,
          runStatus: view.status,
        },
        draggable: false,
        selectable: false,
        focusable: false,
      })),
    [layout, stageById, view.stages, view.status, statuses, selectedId, orientation, animate, uiLocale],
  );

  const edges: StageFlowEdge[] = useMemo(
    () =>
      layout.edges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        type: "stage",
        sourceHandle: e.sourceHandle,
        targetHandle: e.targetHandle,
        selectable: false,
        focusable: false,
        data: { state: edgeState(e, statuses, taken), condition: e.condition, skip: e.skip, orientation, animate },
      })),
    [layout, statuses, taken, orientation, animate, uiLocale],
  );

  const layoutKey = `${workflow.id}:${orientation}:${box.width}x${box.height}`;

  return (
    <div ref={ref} dir="ltr" className={cn("adapt-flow canvas-dots relative min-h-0 flex-1", className)}>
      {box.width > 0 && (
        <ReactFlow<StageFlowNode, StageFlowEdge>
        ariaLabelConfig={graphA11y()}
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          nodesDraggable={false}
          nodesConnectable={false}
          nodesFocusable={false}
          edgesFocusable={false}
          elementsSelectable={false}
          deleteKeyCode={null}
          selectionKeyCode={null}
          multiSelectionKeyCode={null}
          zoomOnDoubleClick={false}
          onNodeClick={(_, node) => onSelect(node.id)}
          minZoom={0.3}
          maxZoom={1.5}
          fitView={fits}
          fitViewOptions={FIT_OPTIONS}
          onMoveStart={(event) => {
            // A person panning or zooming takes the camera; programmatic moves have no event.
            if (event) setFollow(false);
          }}
          aria-label={tr("copy.agent_workflow_4934284")}
        >
          <Camera layoutKey={layoutKey} fits={fits} focusId={focusId} follow={follow} />
          <Controls showInteractive={false} position="bottom-left" />
        </ReactFlow>
      )}
      {!fits && !follow && (
        <button
          type="button"
          onClick={() => setFollow(true)}
          className="absolute end-4 top-4 inline-flex h-9 items-center gap-1.5 rounded-full border border-line-strong bg-surface px-3 text-sm font-medium shadow-card hover:bg-sunken"
        >
          <LocateFixed className="size-4" aria-hidden />
          {tr("copy.follow_the_run_55f2239")}</button>
      )}
    </div>
  );
}

/** The agent workflow as a live graph. Stage cards are buttons: Tab to reach, Enter to open. */
export function WorkflowGraph(props: WorkflowGraphProps) {
  useLocale();
  return (
    <ReactFlowProvider>
      <Graph {...props} />
    </ReactFlowProvider>
  );
}
