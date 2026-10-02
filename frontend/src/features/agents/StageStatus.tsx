import { tr, localize, useLocale } from "@/i18n";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { Ban, Bot, CircleCheck, CircleDashed, Hand, OctagonX, UserRound, Wrench, type LucideIcon } from "lucide-react";
import type { AgentStage } from "@/domain/runs";
import type { StageStatus } from "@/lib/events/runEvents";
import { cn } from "@/lib/cn";

/**
 * The six stage states. Each has its own icon, label and fill so it reads without colour:
 * queued is an outline, running a teal tint with a slow pulse, complete solid teal with a
 * check, blocked a dashed danger outline, "requires approval" solid navy (the strongest call
 * to act, as everywhere in ADAPT) and failed a danger fill.
 */
export const STAGE_STATUS: Record<StageStatus, { label: string; hint: string; icon: LucideIcon | null; pill: string; card: string; rail: string }> = {
  queued: {
    label: tr("copy.queued_6a59987", { lng: "en" }),
    hint: tr("copy.waiting_for_earlier_steps_08a0214", { lng: "en" }),
    icon: CircleDashed,
    pill: "border border-line-strong bg-surface text-muted",
    card: "border-line bg-surface",
    rail: "border-line-strong bg-surface text-subtle",
  },
  running: {
    label: tr("copy.running_73989d9", { lng: "en" }),
    hint: tr("copy.working_on_it_now_eb6293e", { lng: "en" }),
    icon: null,
    pill: "border border-primary/40 bg-primary-tint text-primary-strong",
    card: "border-primary bg-surface shadow-raised",
    rail: "border-primary bg-primary-tint text-primary-strong",
  },
  complete: {
    label: tr("copy.complete_1f5a1ab", { lng: "en" }),
    hint: tr("copy.finished_355bcc5", { lng: "en" }),
    icon: CircleCheck,
    pill: "border border-primary bg-primary text-on-primary",
    card: "border-line-strong bg-surface",
    rail: "border-primary bg-primary text-on-primary",
  },
  blocked: {
    label: tr("copy.blocked_99613c7", { lng: "en" }),
    hint: tr("copy.not_reached_because_the_run_stopped_444661b", { lng: "en" }),
    icon: Ban,
    pill: "border border-dashed border-danger/60 bg-surface text-danger",
    card: "border-dashed border-danger/40 bg-muted-surface",
    rail: "border-dashed border-danger/60 bg-surface text-danger",
  },
  awaiting: {
    label: tr("copy.requires_approval_4ecb6f5", { lng: "en" }),
    hint: tr("copy.paused_until_you_decide_c03247f", { lng: "en" }),
    icon: Hand,
    pill: "border border-ink bg-ink text-canvas",
    card: "border-ink bg-surface shadow-raised",
    rail: "border-ink bg-ink text-canvas",
  },
  failed: {
    label: tr("copy.failed_09fef5d", { lng: "en" }),
    hint: tr("copy.stopped_with_an_error_31219bf", { lng: "en" }),
    icon: OctagonX,
    pill: "border border-danger bg-danger-tint text-danger",
    card: "border-danger bg-danger-tint/40",
    rail: "border-danger bg-danger-tint text-danger",
  },
};

export const KIND_META: Record<AgentStage["kind"], { label: string; icon: LucideIcon }> = {
  agent: { label: tr("copy.agent_step_7ff6e94", { lng: "en" }), icon: Bot },
  tool: { label: tr("copy.tool_step_e23265e", { lng: "en" }), icon: Wrench },
  human: { label: tr("copy.your_decision_a2bb6af", { lng: "en" }), icon: UserRound },
};

/** A calm "live" dot: a solid centre with a slowly breathing halo. */
export function LiveDot({ className }: { className?: string }) {
  useLocale();
  const reduce = useReducedMotion();
  return (
    <span className={cn("relative inline-flex size-2.5 items-center justify-center", className)} aria-hidden>
      {!reduce && (
        <motion.span
          className="absolute inset-0 rounded-full bg-current"
          animate={{ scale: [1, 2.1], opacity: [0.45, 0] }}
          transition={{ duration: 1.8, repeat: Infinity, ease: "easeOut" }}
        />
      )}
      <span className="relative size-2 rounded-full bg-current" />
    </span>
  );
}

export function StageStatusIcon({ status, className }: { status: StageStatus; className?: string }) {
  useLocale();
  const Icon = STAGE_STATUS[status].icon;
  if (!Icon) return <LiveDot className={cn("mx-[3px]", className)} />;
  return <Icon className={cn("size-3.5", className)} aria-hidden />;
}

/** Status pill. The label swaps with a short cross-fade when the status changes. */
export function StagePill({ status, className, animate = true }: { status: StageStatus; className?: string; animate?: boolean }) {
  useLocale();
  const reduce = useReducedMotion() || !animate;
  const meta = STAGE_STATUS[status];
  return (
    <span
      title={localize(meta.hint)}
      className={cn(
        "inline-flex h-6 shrink-0 items-center gap-1 overflow-hidden rounded-full px-2 text-2xs font-medium whitespace-nowrap transition-colors duration-300",
        meta.pill,
        className,
      )}
    >
      <AnimatePresence mode="wait" initial={false}>
        <motion.span
          key={status}
          className="inline-flex items-center gap-1"
          initial={reduce ? false : { opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={reduce ? undefined : { opacity: 0, y: -6 }}
          transition={{ duration: 0.22, ease: [0.2, 0, 0, 1] }}
        >
          <StageStatusIcon status={status} />
          {localize(meta.label)}
        </motion.span>
      </AnimatePresence>
    </span>
  );
}

export function KindIcon({ kind, className }: { kind: AgentStage["kind"]; className?: string }) {
  useLocale();
  const meta = KIND_META[kind];
  const Icon = meta.icon;
  return (
    <span
      title={localize(meta.label)}
      className={cn(
        "inline-flex size-7 shrink-0 items-center justify-center rounded-md",
        kind === "human" ? "bg-ink/[0.07] text-ink" : "bg-sunken text-muted",
        className,
      )}
    >
      <Icon className="size-4" aria-hidden />
      <span className="sr-only">{localize(meta.label)}</span>
    </span>
  );
}
