import { tr, localize, useLocale } from "@/i18n";
import { Link } from "react-router";
import { DOCUMENT_KIND_LABEL, type UserDocument } from "@/domain/documents";
import { cn } from "@/lib/cn";
import { formatBytes, relativeTime } from "@/lib/format";
import { reviewCount } from "../lib/documents";
import { KindTile, PipelineBar } from "./Pipeline";

/**
 * Uploaded documents with their processing status. Each row is one button (stretched over
 * the row) so journey-step links inside it stay separately clickable.
 */
export function DocumentList({
  documents,
  selectedId,
  onSelect,
  nodeTitle,
  opensDialog,
}: {
  documents: UserDocument[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  nodeTitle: (key: string) => string;
  /** On phones a row opens the document in a sheet. */
  opensDialog: boolean;
}) {
  useLocale();
  return (
    <ul className="divide-y divide-line" aria-label={tr("copy.your_documents_8485be9")}>
      {documents.map((doc) => {
        const selected = doc.id === selectedId;
        const used = doc.usedFor.slice(0, 2);
        const more = doc.usedFor.length - used.length;
        return (
          <li
            key={doc.id}
            className={cn("relative flex gap-3 px-4 py-4 transition-colors sm:px-5", selected ? "bg-primary-tint/60" : "hover:bg-muted-surface")}
          >
            {selected && <span className="absolute inset-y-2 start-0 w-0.5 rounded-full bg-primary" aria-hidden />}
            <KindTile kind={doc.kind} className={selected ? "bg-surface" : undefined} />
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline justify-between gap-3">
                <button
                  type="button"
                  onClick={() => onSelect(doc.id)}
                  aria-current={!opensDialog && selected ? "true" : undefined}
                  aria-haspopup={opensDialog ? "dialog" : undefined}
                  className="min-w-0 truncate text-start font-medium after:absolute after:inset-0 after:content-['']"
                >
                  {localize(DOCUMENT_KIND_LABEL[doc.kind])}
                </button>
                <span className="shrink-0 text-2xs text-subtle">{localize(relativeTime(doc.createdAt))}</span>
              </div>
              <p className="mt-0.5 flex min-w-0 gap-2 text-xs text-muted">
                <span className="truncate">{doc.filename}</span>
                <span className="tabular shrink-0">{localize(formatBytes(doc.sizeBytes))}</span>
              </p>
              <PipelineBar className="mt-2.5" status={doc.status} reviewCount={reviewCount(doc.extraction?.fields)} />
              {used.length > 0 && (
                <p className="mt-2 text-xs text-muted">
                  {tr("copy.used_for_d678e1d")}{localize(" ")}
                  {used.map((key, i) => (
                    <span key={key}>
                      <Link
                        to={`/journey?node=${encodeURIComponent(key)}`}
                        className="relative z-10 text-ink underline decoration-line-strong underline-offset-2 hover:decoration-ink"
                      >
                        {localize(nodeTitle(key))}
                      </Link>
                      {i < used.length - 1 || more > 0 ? ", " : ""}
                    </span>
                  ))}
                  {more > 0 && tr("copy.and_v0_more_14ee4ff", { v0: more })}
                </p>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
