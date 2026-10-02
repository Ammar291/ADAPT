import { tr, localize, useLocale } from "@/i18n";
import { BadgeCheck, Scale, Sparkles, Users } from "lucide-react";
import type { ReactNode } from "react";
import type { EvidenceKind } from "@/domain/common";
import { cn } from "@/lib/cn";

/**
 * The trust tier of a claim. Tiers differ by fill and line style as well as colour, so
 * they stay distinguishable in greyscale and for colour-blind users:
 *   law        — solid navy fill
 *   official   — solid civic outline
 *   community  — amber outline on amber tint
 *   ADAPT      — dashed outline
 * A community result must never look like a requirement.
 */
const tiers: Record<EvidenceKind, { label: string; hint: string; icon: ReactNode; className: string }> = {
  authoritative_requirement: {
    label: tr("copy.official_rule_3a21f1b", { lng: "en" }),
    hint: tr("copy.a_requirement_supported_by_an_official_uae_gover_fa48e47", { lng: "en" }),
    icon: <Scale className="size-3.5" aria-hidden />,
    className: "bg-ink text-canvas border border-ink",
  },
  official_guidance: {
    label: tr("copy.official_guidance_37f7d4d", { lng: "en" }),
    hint: tr("copy.guidance_supported_by_an_official_uae_government_b26b92a", { lng: "en" }),
    icon: <BadgeCheck className="size-3.5" aria-hidden />,
    className: "border border-civic text-civic bg-surface",
  },
  community_web: {
    label: tr("copy.community_information_d310ade", { lng: "en" }),
    hint: tr("copy.found_online_from_organisations_or_residents_not_5877b1d", { lng: "en" }),
    icon: <Users className="size-3.5" aria-hidden />,
    className: "border border-dune/60 text-dune bg-dune-tint",
  },
  ai_recommendation: {
    label: tr("copy.adapt_suggestion_d692316", { lng: "en" }),
    hint: tr("copy.adapt_s_own_recommendation_based_on_your_situati_67f6810", { lng: "en" }),
    icon: <Sparkles className="size-3.5" aria-hidden />,
    className: "border border-dashed border-line-strong text-muted bg-surface",
  },
};

export function TrustBadge({ kind, className, compact = false, cultural = false }: { kind: EvidenceKind; className?: string; compact?: boolean; cultural?: boolean }) {
  useLocale();
  const tier = tiers[kind];
  const label = culturalTrustLabel(kind, cultural);
  return (
    <span
      title={localize(tier.hint)}
      className={cn(
        "inline-flex h-6 shrink-0 items-center gap-1 rounded-md px-2 text-2xs font-medium whitespace-nowrap",
        tier.className,
        className,
      )}
    >
      {localize(tier.icon)}
      {compact ? <span className="sr-only">{localize(label)}</span> : label}
      <span className="sr-only">{tr("copy.text_ceca32e")}{localize(tier.hint)}</span>
    </span>
  );
}

export function culturalTrustLabel(kind: EvidenceKind, cultural = true): string {
  if (cultural && kind === "community_web") return tr("copy.social_practice_ea3104b");
  if (cultural && kind === "ai_recommendation") return tr("copy.ai_recommendation_f55ae5c");
  return tiers[kind].label;
}

export const trustTierOrder: EvidenceKind[] = ["authoritative_requirement", "official_guidance", "community_web", "ai_recommendation"];

export function trustTierLabel(kind: EvidenceKind): string {
  return tiers[kind].label;
}

export function trustTierHint(kind: EvidenceKind): string {
  return tiers[kind].hint;
}
