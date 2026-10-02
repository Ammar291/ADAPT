import { tr, useLocale } from "@/i18n";
import { lazy, Suspense } from "react";
import { Skeleton, SkeletonText } from "@/components/ui/States";

// The conversation surface (voice + text) is owned by features/voice and loads on first use:
// it carries WebRTC and audio code that most screens never need.
const ConversationPanel = lazy(() => import("@/features/voice/ConversationPanel"));

function PanelSkeleton() {
  useLocale();
  return (
    <div role="status" aria-label={tr("copy.loading_the_assistant_c53b245")} className="flex h-full flex-col justify-end gap-4 p-5">
      <Skeleton className="h-6 w-2/3" />
      <SkeletonText lines={2} />
      <Skeleton className="mt-4 h-12 w-full rounded-xl" />
    </div>
  );
}

/** The assistant conversation, sized to fill its container (dock, sheet or page). */
export function AssistantPanel({ variant, onClose }: { variant: "dock" | "sheet" | "page"; onClose?: () => void }) {
  useLocale();
  return (
    <div className="flex h-full min-h-0 flex-col">
      <Suspense fallback={<PanelSkeleton />}>
        <ConversationPanel variant={variant} onClose={onClose} className="min-h-0 flex-1" />
      </Suspense>
    </div>
  );
}
