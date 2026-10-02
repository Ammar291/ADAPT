import { tr, localize, useLocale } from "@/i18n";
import { AlertCircle, Check, CircleSlash, Info, KeyRound, LoaderCircle, ShieldCheck } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";
import { Link } from "react-router";
import { cn } from "@/lib/cn";
import type { ConversationItem, NoticeItem, ToolItem, TurnItem } from "../conversation";
import { ApprovalCard, ConsentCard } from "./DecisionCards";

const HINT_LABEL: Record<string, string> = {
  "/journey": tr("copy.open_your_plan_73f3bff", { lng: "en" }),
  "/activity": tr("copy.follow_progress_in_activity_4b8631b", { lng: "en" }),
  "/documents": tr("copy.go_to_documents_0b5c489", { lng: "en" }),
  "/discover": tr("copy.open_discover_5525c87", { lng: "en" }),
  "/services": tr("copy.browse_services_3c06d3f", { lng: "en" }),
  "/twin": tr("copy.see_what_adapt_knows_about_you_e003efc", { lng: "en" }),
  "/what-if": tr("copy.open_what_if_b395321", { lng: "en" }),
  "/settings": tr("copy.open_settings_134635e", { lng: "en" }),
};

function Turn({ turn }: { turn: TurnItem }) {
  useLocale();
  const streaming = !turn.final && !turn.interrupted;
  const isUser = turn.speaker === "user";
  if (isUser && !turn.text) {
    return (
      <p className="text-sm text-subtle" aria-hidden>
        <span className="voice-caret">{tr("copy.you_905cb32")}</span>
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-1">
      <p className="text-xs text-subtle">{isUser ? tr("copy.you_905cb32") : tr("copy.adapt_2e26648")}</p>
      <p
        dir="auto"
        className={cn(
          "whitespace-pre-line text-start",
          isUser ? "text-base text-muted" : "text-lg leading-relaxed text-ink",
          streaming && "voice-caret",
        )}
      >
        {turn.text}
      </p>
      {turn.interrupted && <p className="text-xs text-subtle">{tr("copy.stopped_when_you_spoke_a3d4568")}</p>}
    </div>
  );
}

const TOOL_ICON: Record<string, ReactNode> = {
  running: <LoaderCircle className="size-4 animate-spin text-primary" aria-hidden />,
  ok: <Check className="size-4 text-primary" aria-hidden />,
  not_found: <CircleSlash className="size-4 text-subtle" aria-hidden />,
  needs_approval: <ShieldCheck className="size-4 text-ink" aria-hidden />,
  needs_consent: <KeyRound className="size-4 text-ink" aria-hidden />,
};

function Tool({ tool, onNavigate }: { tool: ToolItem; onNavigate?: () => void }) {
  useLocale();
  const hint = tool.uiHint && HINT_LABEL[tool.uiHint] ? tool.uiHint : null;
  return (
    <div className="flex gap-2.5 text-sm" aria-live="off">
      <span className="mt-0.5 shrink-0">
        {TOOL_ICON[tool.status] ?? <AlertCircle className="size-4 text-danger" aria-hidden />}
      </span>
      <div className="min-w-0">
        <p className={tool.status === "running" ? "text-ink" : "text-muted"}>{localize(tool.label)}</p>
        {tool.summary && tool.status !== "running" && <p className="text-subtle">{localize(tool.summary)}</p>}
        {hint && tool.status === "ok" && (
          <Link
            to={hint}
            onClick={onNavigate}
            className="text-primary underline decoration-primary/40 underline-offset-4 hover:decoration-primary"
          >
            {localize(HINT_LABEL[hint])}
          </Link>
        )}
      </div>
    </div>
  );
}

function Notice({ notice }: { notice: NoticeItem }) {
  useLocale();
  return (
    <p className={cn("flex gap-2 text-sm", notice.tone === "warning" ? "text-danger" : "text-muted")}>
      <Info className="mt-0.5 size-4 shrink-0" aria-hidden />
      {localize(notice.text)}
    </p>
  );
}

/**
 * The conversation as captions: start-aligned paragraphs rather than chat bubbles, with
 * `dir="auto"` per turn so Arabic, Urdu or any other script reads in its own direction.
 */
export function Transcript({
  items,
  empty,
  onNavigate,
}: {
  items: ConversationItem[];
  empty: ReactNode;
  onNavigate?: () => void;
}) {
  useLocale();
  const scroller = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);
  const last = items.at(-1);
  const lastSize = last?.kind === "turn" ? last.text.length : 0;

  useEffect(() => {
    const element = scroller.current;
    if (element && pinned.current) element.scrollTo({ top: element.scrollHeight });
  }, [items.length, lastSize]);

  return (
    <div
      ref={scroller}
      onScroll={(event) => {
        const el = event.currentTarget;
        pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
      }}
      className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 py-6"
    >
      {items.length === 0 ? (
        empty
      ) : (
        <ol className="flex flex-col gap-5" aria-label={tr("copy.conversation_2a20c75")}>
          {items.map((item) => (
            <li key={item.id}>
              {item.kind === "turn" && <Turn turn={item} />}
              {item.kind === "tool" && <Tool tool={item} onNavigate={onNavigate} />}
              {item.kind === "approval" && <ApprovalCard item={item} />}
              {item.kind === "consent" && <ConsentCard item={item} />}
              {item.kind === "notice" && <Notice notice={item} />}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
