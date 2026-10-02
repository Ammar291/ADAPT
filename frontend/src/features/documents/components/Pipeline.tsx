import { tr, localize, useLocale } from "@/i18n";
import {
  BookUser,
  BriefcaseBusiness,
  Building2,
  CircleAlert,
  CircleCheck,
  CircleDashed,
  CircleDot,
  FileText,
  House,
  IdCard,
  LoaderCircle,
  ScrollText,
  TriangleAlert,
} from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import type { DocumentKind, DocumentStatus } from "@/domain/documents";
import { cn } from "@/lib/cn";
import { pipelineOf, type Pipeline, type PipelineTone, type StepState } from "../lib/documents";

export const KIND_ICON: Record<DocumentKind, typeof FileText> = {
  passport: BookUser,
  marriage_certificate: ScrollText,
  employment_letter: BriefcaseBusiness,
  business_document: Building2,
  tenancy_document: House,
  identity_document: IdCard,
  miscellaneous: FileText,
};

export function KindTile({ kind, className }: { kind: DocumentKind; className?: string }) {
  useLocale();
  const Icon = KIND_ICON[kind];
  return (
    <span className={cn("flex size-10 shrink-0 items-center justify-center rounded-lg bg-sunken text-muted", className)} aria-hidden>
      <Icon className="size-5" />
    </span>
  );
}

const LABEL_TONE: Record<PipelineTone, string> = {
  working: "text-muted",
  attention: "text-ink font-medium",
  ready: "text-primary-strong font-medium",
  done: "text-primary-strong",
  failed: "text-danger font-medium",
};

function segmentClass(state: StepState, tone: PipelineTone): string {
  if (state === "done") return "bg-primary";
  if (state === "failed") return "bg-danger";
  if (state === "todo") return "bg-line";
  if (tone === "attention") return "bg-ink";
  if (tone === "working") return "bg-primary/40 animate-pulse";
  return "bg-primary/55";
}

/** Compact four-segment indicator with the status in words, for list rows. */
export function PipelineBar({ status, reviewCount = 0, className }: { status: DocumentStatus; reviewCount?: number; className?: string }) {
  useLocale();
  const pipeline = pipelineOf(status, reviewCount);
  const reduce = useReducedMotion();
  return (
    <div className={cn("flex items-center gap-3", className)}>
      <div className="flex w-20 shrink-0 gap-1" aria-hidden>
        {pipeline.steps.map((step) => (
          <span key={step.key} className={cn("h-1 flex-1 rounded-full transition-colors duration-500", segmentClass(step.state, pipeline.tone))} />
        ))}
      </div>
      <motion.span
        key={pipeline.label}
        initial={reduce ? false : { opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.25 }}
        className={cn("flex min-w-0 items-center gap-1.5 truncate text-xs", LABEL_TONE[pipeline.tone])}
      >
        {pipeline.busy && <LoaderCircle className="size-3.5 shrink-0 animate-spin" aria-hidden />}
        {localize(pipeline.label)}
      </motion.span>
    </div>
  );
}

const STATE_TEXT: Record<StepState, string> = { done: "done", current: tr("copy.current_step_4ec2fb9", { lng: "en" }), todo: tr("copy.not_yet_3a23035", { lng: "en" }), failed: tr("copy.didn_t_work_fd25687", { lng: "en" }) };

function StepIcon({ state, pipeline }: { state: StepState; pipeline: Pipeline }) {
  useLocale();
  const cls = "size-5 shrink-0";
  if (state === "done") return <CircleCheck className={cn(cls, "text-primary")} aria-hidden />;
  if (state === "failed") return <TriangleAlert className={cn(cls, "text-danger")} aria-hidden />;
  if (state === "todo") return <CircleDashed className={cn(cls, "text-subtle")} aria-hidden />;
  if (pipeline.busy) return <LoaderCircle className={cn(cls, "animate-spin text-primary")} aria-hidden />;
  if (pipeline.tone === "attention") return <CircleAlert className={cn(cls, "text-ink")} aria-hidden />;
  return <CircleDot className={cn(cls, "text-primary")} aria-hidden />;
}

/** The full uploaded → read → checked → confirmed sequence, with what happens next. */
export function PipelineSteps({ status, reviewCount = 0, className }: { status: DocumentStatus; reviewCount?: number; className?: string }) {
  useLocale();
  const pipeline = pipelineOf(status, reviewCount);
  return (
    <div className={className}>
      <ol className="grid grid-cols-4" aria-label={tr("copy.processing_steps_7f9a122")}>
        {pipeline.steps.map((step, i) => (
          <li key={step.key} className="relative flex flex-col items-start gap-1.5">
            <div className="flex w-full items-center">
              <StepIcon state={step.state} pipeline={pipeline} />
              {i < pipeline.steps.length - 1 && (
                <span
                  className={cn("mx-1.5 h-px flex-1 transition-colors duration-500", step.state === "done" ? "bg-primary" : "bg-line-strong")}
                  aria-hidden
                />
              )}
            </div>
            <span className={cn("text-2xs", step.state === "current" || step.state === "failed" ? "font-medium text-ink" : "text-muted")}>
              {localize(step.label)}
              <span className="sr-only">{tr("copy.text_ceca32e")}{localize(STATE_TEXT[step.state])}</span>
            </span>
          </li>
        ))}
      </ol>
      <p className="mt-3 text-sm" aria-live="polite">
        <span className={cn("font-medium", LABEL_TONE[pipeline.tone])}>{localize(pipeline.label)}{tr("copy.text_3a52ce7")}</span> <span className="text-muted">{localize(pipeline.detail)}</span>
      </p>
    </div>
  );
}
