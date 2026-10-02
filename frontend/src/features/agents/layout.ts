/**
 * Pure layout for the agent workflow graph. Stages are placed by topological level along the
 * main axis and by `lane` across it, so parallel branches sit side by side. Edges that skip
 * over a stage in their own lane are flagged so the renderer routes them around it.
 */
import type { AgentWorkflow } from "@/domain/runs";

export type Orientation = "horizontal" | "vertical";

export interface LayoutSizes {
  nodeWidth: number;
  nodeHeight: number;
  /** Space between levels, along the main axis. */
  gapMain: number;
  /** Space between lanes, across the main axis. */
  gapCross: number;
}

export interface PlacedStage {
  id: string;
  level: number;
  lane: number;
  x: number;
  y: number;
}

export interface PlacedEdge {
  id: string;
  source: string;
  target: string;
  condition: string | null;
  /** Jumps over a stage in its own lane: route it around the side instead of through. */
  skip: boolean;
  /**
   * Which side each end attaches to: `main` follows the flow (bottom to top, or right to
   * left); `side` is the lane side, used to branch into and merge out of parallel lanes and
   * to route skips around stages.
   */
  sourceHandle: "out" | "side-out";
  targetHandle: "in" | "side-in";
}

export interface WorkflowLayout {
  orientation: Orientation;
  stages: PlacedStage[];
  edges: PlacedEdge[];
  /** Stage ids per level, in lane order. */
  levels: string[][];
  width: number;
  height: number;
}

/** Node sizes per orientation: wide and short when stacked, narrower and taller side by side. */
export const LAYOUT_SIZES: Record<Orientation, LayoutSizes> = {
  vertical: { nodeWidth: 340, nodeHeight: 60, gapMain: 22, gapCross: 28 },
  horizontal: { nodeWidth: 232, nodeHeight: 88, gapMain: 52, gapCross: 28 },
};

/**
 * Longest-path level of every stage (0 = entry). Edges that would close a cycle are ignored,
 * so a malformed workflow still lays out.
 */
export function stageLevels(workflow: AgentWorkflow): Map<string, number> {
  const ids = workflow.stages.map((s) => s.id);
  const known = new Set(ids);
  const incoming = new Map<string, string[]>(ids.map((id) => [id, []]));
  for (const edge of workflow.edges) {
    if (known.has(edge.source) && known.has(edge.target) && edge.source !== edge.target) incoming.get(edge.target)!.push(edge.source);
  }
  const level = new Map<string, number>();
  const visiting = new Set<string>();
  const visit = (id: string): number => {
    const cached = level.get(id);
    if (cached !== undefined) return cached;
    if (visiting.has(id)) return -1; // back edge: ignore
    visiting.add(id);
    let value = 0;
    for (const source of incoming.get(id) ?? []) {
      const l = visit(source);
      if (l >= 0) value = Math.max(value, l + 1);
    }
    visiting.delete(id);
    level.set(id, value);
    return value;
  };
  ids.forEach(visit);
  return level;
}

export function layoutWorkflow(workflow: AgentWorkflow, orientation: Orientation, sizes: LayoutSizes = LAYOUT_SIZES[orientation]): WorkflowLayout {
  const levelOf = stageLevels(workflow);
  const maxLevel = Math.max(-1, ...levelOf.values());
  const levels: string[][] = Array.from({ length: maxLevel + 1 }, () => []);
  const laneOf = new Map(workflow.stages.map((s) => [s.id, Math.max(0, s.lane)]));
  for (const stage of workflow.stages) levels[levelOf.get(stage.id)!]!.push(stage.id);
  for (const ids of levels) ids.sort((a, b) => laneOf.get(a)! - laneOf.get(b)!);

  const main = orientation === "horizontal" ? sizes.nodeWidth : sizes.nodeHeight;
  const cross = orientation === "horizontal" ? sizes.nodeHeight : sizes.nodeWidth;

  // Stages sharing a level and a lane (unusual) are nudged into the next free lane slot.
  const slot = new Map<string, number>();
  for (const ids of levels) {
    const used = new Set<number>();
    for (const id of ids) {
      let lane = laneOf.get(id)!;
      while (used.has(lane)) lane += 1;
      used.add(lane);
      slot.set(id, lane);
    }
  }

  const stages: PlacedStage[] = workflow.stages.map((stage) => {
    const level = levelOf.get(stage.id)!;
    const lane = slot.get(stage.id)!;
    const along = level * (main + sizes.gapMain);
    const across = lane * (cross + sizes.gapCross);
    return {
      id: stage.id,
      level,
      lane,
      x: orientation === "horizontal" ? along : across,
      y: orientation === "horizontal" ? across : along,
    };
  });
  stages.sort((a, b) => a.level - b.level || a.lane - b.lane);

  const placed = new Map(stages.map((s) => [s.id, s]));
  const edges: PlacedEdge[] = workflow.edges
    .filter((e) => placed.has(e.source) && placed.has(e.target))
    .map((e) => {
      const s = placed.get(e.source)!;
      const t = placed.get(e.target)!;
      const skip =
        t.level - s.level > 1 && stages.some((other) => other.level > s.level && other.level < t.level && other.lane === s.lane && s.lane === t.lane);
      const sourceHandle = skip || t.lane > s.lane ? "side-out" : "out";
      const targetHandle = skip || s.lane > t.lane ? "side-in" : "in";
      return { id: `${e.source}->${e.target}`, source: e.source, target: e.target, condition: e.condition, skip, sourceHandle, targetHandle };
    });

  const lanes = Math.max(1, ...stages.map((s) => s.lane + 1));
  const levelCount = Math.max(1, levels.length);
  const alongSize = levelCount * main + (levelCount - 1) * sizes.gapMain;
  const acrossSize = lanes * cross + (lanes - 1) * sizes.gapCross;
  return {
    orientation,
    stages,
    edges,
    levels,
    width: orientation === "horizontal" ? alongSize : acrossSize,
    height: orientation === "horizontal" ? acrossSize : alongSize,
  };
}

/** The zoom at which a layout fits a box, with padding on each side (never above 1). */
export function fitZoom(layout: Pick<WorkflowLayout, "width" | "height">, box: { width: number; height: number }, padding = 48): number {
  if (box.width <= 0 || box.height <= 0) return 1;
  const zx = (box.width - padding * 2) / Math.max(1, layout.width);
  const zy = (box.height - padding * 2) / Math.max(1, layout.height);
  return Math.max(0.05, Math.min(1, zx, zy));
}

/** Readable zoom threshold: below it labels get too small to read comfortably. */
export const READABLE_ZOOM = 0.8;

/**
 * Levels run left to right when the whole workflow fits at a readable size; otherwise the
 * graph turns top to bottom, which suits long pipelines in a narrow pane.
 */
export function chooseOrientation(workflow: AgentWorkflow, box: { width: number; height: number }): Orientation {
  const horizontal = fitZoom(layoutWorkflow(workflow, "horizontal"), box);
  if (horizontal >= READABLE_ZOOM) return "horizontal";
  const vertical = fitZoom(layoutWorkflow(workflow, "vertical"), box);
  return vertical > horizontal ? "vertical" : "horizontal";
}
