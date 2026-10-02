import { tr, useLocale } from "@/i18n";
import { Square, SquareCheck } from "lucide-react";
import { Fragment, useMemo } from "react";
import { cn } from "@/lib/cn";
import { parseMarkdown, type Block, type Inline } from "../lib/markdown";

function Inlines({ content }: { content: Inline[] }) {
  useLocale();
  return (
    <>
      {content.map((node, i) => {
        switch (node.type) {
          case "strong":
            return (
              <strong key={i} className="font-semibold">
                {node.text}
              </strong>
            );
          case "em":
            return <em key={i}>{node.text}</em>;
          case "code":
            return (
              <code key={i} className="rounded bg-sunken px-1 py-0.5 text-[0.92em]">
                {node.text}
              </code>
            );
          case "link":
            return (
              <a key={i} href={node.href} target="_blank" rel="noopener noreferrer" className="font-medium text-primary-strong underline underline-offset-4">
                {node.text}
                <span className="sr-only"> {tr("copy.opens_in_a_new_tab_bf5b990")}</span>
              </a>
            );
          default:
            return <Fragment key={i}>{node.text}</Fragment>;
        }
      })}
    </>
  );
}

function Lines({ lines }: { lines: Inline[][] }) {
  useLocale();
  return (
    <>
      {lines.map((line, i) => (
        <Fragment key={i}>
          {i > 0 && <br />}
          <Inlines content={line} />
        </Fragment>
      ))}
    </>
  );
}

function BlockView({ block }: { block: Block }) {
  useLocale();
  switch (block.type) {
    case "heading": {
      // The draft sits under the panel's h2, so its headings start at h3.
      const Tag = (["h3", "h4", "h5"] as const)[block.level - 1]!;
      return (
        <Tag className={cn("font-display text-ink", block.level === 1 ? "text-xl" : block.level === 2 ? "text-lg" : "text-base font-medium")}>
          <Inlines content={block.content} />
        </Tag>
      );
    }
    case "paragraph":
      return (
        <p>
          <Lines lines={block.lines} />
        </p>
      );
    case "quote":
      return (
        <blockquote className="border-s-2 border-line-strong ps-3 text-muted">
          <Lines lines={block.lines} />
        </blockquote>
      );
    case "rule":
      return <hr className="border-line" />;
    case "list": {
      const checklist = block.items.some((item) => item.checked !== null);
      if (checklist) {
        return (
          <ul className="flex flex-col gap-2">
            {block.items.map((item, i) => (
              <li key={i} className="flex items-start gap-2.5">
                {item.checked ? (
                  <SquareCheck className="mt-0.5 size-4.5 shrink-0 text-primary" aria-hidden />
                ) : (
                  <Square className="mt-0.5 size-4.5 shrink-0 text-subtle" aria-hidden />
                )}
                <span className="sr-only">{item.checked ? tr("copy.done_235531f") : tr("copy.to_do_9a7e044")}</span>
                <span className={cn(item.checked && "text-muted line-through decoration-line-strong")}>
                  <Inlines content={item.content} />
                </span>
              </li>
            ))}
          </ul>
        );
      }
      const List = block.ordered ? "ol" : "ul";
      return (
        <List className={cn("flex flex-col gap-1 ps-5", block.ordered ? "list-decimal" : "list-disc marker:text-subtle")}>
          {block.items.map((item, i) => (
            <li key={i}>
              <Inlines content={item.content} />
            </li>
          ))}
        </List>
      );
    }
  }
}

/** Renders a draft's markdown as React elements. Nothing is injected as HTML. */
export function Markdown({ source, className }: { source: string; className?: string }) {
  const uiLocale = useLocale();
  const blocks = useMemo(() => parseMarkdown(source), [source, uiLocale]);
  if (!blocks.length) return <p className={cn("text-subtle", className)}>{tr("copy.this_draft_is_empty_664eb6c")}</p>;
  return (
    <div className={cn("flex flex-col gap-3.5 leading-relaxed", className)}>
      {blocks.map((block, i) => (
        <BlockView key={i} block={block} />
      ))}
    </div>
  );
}
