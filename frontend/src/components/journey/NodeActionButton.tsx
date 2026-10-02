import { tr, localize, useLocale } from "@/i18n";
import { CalendarPlus, Check, ExternalLink, FileUp, MessageSquareText, PenLine, ShieldCheck } from "lucide-react";
import { Link } from "react-router";
import type { JourneyNode } from "@/domain/journey";
import { Button, buttonClass } from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { useMarkNodeDone, usePrepareAction } from "@/lib/api/hooks";
import { describeError } from "@/lib/api/errors";
import { domainOf } from "@/domain/common";

type Size = "sm" | "md";

/**
 * The single most useful thing to do with a journey step, as one button. Official handoffs
 * open the government site in a new tab; ADAPT never submits on the user's behalf there.
 */
export function NodeActionButton({
  node,
  journeyId,
  size = "md",
  variant = "primary",
  onAnswer,
}: {
  node: JourneyNode;
  journeyId: string;
  size?: Size;
  variant?: "primary" | "secondary";
  /** Called for "answer a question" actions; without it the button links to the step. */
  onAnswer?: () => void;
}) {
  useLocale();
  const prepare = usePrepareAction();
  const markDone = useMarkNodeDone();
  const action = node.action;
  if (!action || node.status === "done" || node.status === "not_applicable") return null;
  const blocked = node.status === "blocked";
  const cls = buttonClass(variant, size);

  if (blocked && action.kind !== "upload_document" && action.kind !== "review_draft") {
    return (
      <Button size={size} variant="secondary" disabled title={localize(node.blockers[0]?.message)}>
        {tr("copy.waiting_on_earlier_steps_e6df663")}</Button>
    );
  }

  const prepareButton = (label: string) => (
    <Button
      size={size}
      variant={variant}
      loading={prepare.isPending}
      icon={<CalendarPlus className="size-4" aria-hidden />}
      onClick={() =>
        prepare.mutate(node.key, {
          onSuccess: () =>
            toast({ title: tr("copy.prepared_for_your_review_3471d12"), description: tr("copy.check_what_will_be_shared_then_approve_it__27a5833"), action: { label: tr("copy.review_now_c594fad"), to: "/documents?tab=approvals" } }),
          onError: (error) => toast({ title: describeError(error).title, description: describeError(error).detail, tone: "error" }),
        })
      }
    >
      {localize(label)}
    </Button>
  );

  // An action type with nothing prepared yet: ADAPT prepares it (no side effects) for approval.
  const unprepared = action.status === null && !action.approvalId && !action.draftId;
  if (unprepared && ["official_handoff", "government_portal", "document_submission", "appointment"].includes(action.kind)) {
    return prepareButton(action.label);
  }

  switch (action.kind) {
    case "official_handoff":
    case "government_portal":
      return action.url ? (
        <a href={action.url} target="_blank" rel="noopener noreferrer" className={cls} title={localize(tr("copy.v0_you_complete_this_on_v1_edb5136", { v0: action.label, v1: domainOf(action.url) }))}>
          {tr("copy.continue_on_9d5570d")}{localize(domainOf(action.url))}
          <ExternalLink className="size-4" aria-hidden />
          <span className="sr-only">{tr("copy.opens_the_official_site_in_a_new_tab_2cd60b0")}</span>
        </a>
      ) : null;
    case "appointment":
      if (action.approvalId) {
        return (
          <Link to="/documents?tab=approvals" className={cls}>
            <ShieldCheck className="size-4" aria-hidden />
            {tr("copy.review_the_booking_ec4ef08")}</Link>
        );
      }
      return prepareButton(action.label);
    case "communication":
    case "review_draft":
    case "document_submission":
      if (action.approvalId && action.status === "awaiting_approval") {
        return (
          <Link to="/documents?tab=approvals" className={cls}>
            <ShieldCheck className="size-4" aria-hidden />
            {tr("copy.review_and_approve_365a840")}</Link>
        );
      }
      return (
        <Link to={action.draftId ? `/documents?draft=${action.draftId}` : "/documents?tab=drafts"} className={cls}>
          <PenLine className="size-4" aria-hidden />
          {localize(action.label)}
        </Link>
      );
    case "upload_document":
      return (
        <Link to={`/documents?upload=${action.documentKind ?? "miscellaneous"}`} className={cls}>
          <FileUp className="size-4" aria-hidden />
          {localize(action.label)}
        </Link>
      );
    case "answer_question":
      return onAnswer ? (
        <Button size={size} variant={variant} icon={<MessageSquareText className="size-4" aria-hidden />} onClick={onAnswer}>
          {localize(action.label)}
        </Button>
      ) : (
        <Link to={`/journey?node=${node.key}`} className={cls}>
          <MessageSquareText className="size-4" aria-hidden />
          {localize(action.label)}
        </Link>
      );
    case "mark_done":
      return (
        <Button
          size={size}
          variant={variant}
          loading={markDone.isPending}
          icon={<Check className="size-4" aria-hidden />}
          onClick={() => markDone.mutate([journeyId, node.key], { onSuccess: () => toast({ title: tr("copy.marked_as_done_06dcd52"), description: node.title }), onError: (error) => toast({ title: tr("copy.couldn_t_update_this_step_2f7f459"), description: describeError(error).detail ?? tr("copy.try_again_when_you_re_connected__ea85464"), tone: "error" }) })}
        >
          {localize(action.label)}
        </Button>
      );
    case "navigate":
      if (action.url?.startsWith("http")) {
        return (
          <a href={action.url} target="_blank" rel="noopener noreferrer" className={cls}>
            {localize(action.label)}
            <ExternalLink className="size-4" aria-hidden />
          </a>
        );
      }
      return (
        <Link to={action.url ?? (node.area === "community" ? "/discover" : "/journey")} className={cls}>
          {localize(action.label)}
        </Link>
      );
    default:
      return null;
  }
}

/** The UAE PASS reassurance shown next to official handoffs that need the user's login. */
export function needsUaePassNote(node: JourneyNode): boolean {
  return Boolean(node.action?.requiresUserAuthentication && node.status !== "done");
}
