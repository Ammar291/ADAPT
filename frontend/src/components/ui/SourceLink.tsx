import { tr, localize, useLocale } from "@/i18n";
import { ExternalLink } from "lucide-react";
import { domainOf, safeWebUrl } from "@/domain/common";
import { cn } from "@/lib/cn";
import { formatDate } from "@/lib/format";

/**
 * A cited source: its title, domain and when ADAPT last checked it, opening in a new tab.
 * External links always use rel="noopener noreferrer".
 */
export function SourceLink({
  title,
  url,
  checkedAt,
  authority,
  className,
}: {
  title: string;
  url: string | null;
  checkedAt?: string | null;
  authority?: string | null;
  className?: string;
}) {
  useLocale();
  const link = safeWebUrl(url);
  const meta = [link ? domainOf(link) : null, checkedAt ? `Last checked ${formatDate(checkedAt)}` : tr("copy.last_checked_unavailable_74a80c9")].filter(Boolean);
  const body = (
    <>
      <span className="min-w-0">
        <span className="block font-medium text-ink group-hover:underline group-hover:underline-offset-4">
          {localize(title)}
        </span>
        {authority && authority !== title && <span className="mt-0.5 block text-2xs text-muted">{localize(authority)}</span>}
        {meta.length > 0 && (
          <span className="mt-0.5 flex flex-wrap gap-x-3 text-2xs text-subtle">
            {meta.map((m) => (
              <span key={m}>{localize(m)}</span>
            ))}
          </span>
        )}
      </span>
      {link && <ExternalLink className="mt-0.5 size-3.5 shrink-0 text-subtle" aria-hidden />}
    </>
  );
  if (!link) return <div className={cn("flex items-start gap-2 text-sm", className)}>{localize(body)}</div>;
  return (
    <a
      href={link}
      target="_blank"
      rel="noopener noreferrer"
      className={cn("group flex min-h-11 items-start justify-between gap-2 rounded-md py-1 text-sm", className)}
    >
      {localize(body)}
      <span className="sr-only">{tr("copy.opens_in_a_new_tab_bf5b990")}</span>
    </a>
  );
}
