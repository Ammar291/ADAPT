import { tr, useLocale } from "@/i18n";
import { Navigate } from "react-router";
import { useActiveJourney, useRecentRuns } from "@/lib/api/hooks";
import { Splash } from "./SessionGate";
import { config } from "@/lib/config";

const ACTIVE = new Set(["queued", "running", "awaiting_input"]);

/**
 * `/` sends people where they're most useful:
 *   a plan exists           → Home
 *   a plan is being built   → Agents, to watch it happen
 *   nothing yet             → Onboarding
 */
export function RootRedirect() {
  useLocale();
  const journey = useActiveJourney();
  const runs = useRecentRuns();

  if (config.demoMode) return <Navigate to="/demo/founder-arrival" replace />;

  if (journey.isPending || runs.isPending) return <Splash label={tr("copy.opening_your_plan_45c9983")} />;
  if (journey.data) return <Navigate to="/home" replace />;
  const building = runs.data?.find((run) => run.kind === "journey" && ACTIVE.has(run.status));
  if (building) return <Navigate to={`/agents?run=${building.id}`} replace />;
  // Journeys unavailable (live mode, not shipped): Home explains what's possible.
  if (journey.isError) return <Navigate to="/home" replace />;
  return <Navigate to="/onboarding" replace />;
}
