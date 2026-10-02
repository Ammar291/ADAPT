import { tr } from "@/i18n";
import { createBrowserRouter, Navigate, type RouteObject } from "react-router";
import { AppShell } from "./layout/AppShell";
import { RootRedirect } from "./RootRedirect";
import { NotFound, RouteError } from "./RouteError";
import { Splash } from "./SessionGate";
import { config } from "@/lib/config";

/** Shown while a page's code loads on the first visit (pages are lazy chunks). */
const loading = <Splash label={tr("copy.opening_adapt_2a4dbce", { lng: "en" })} />;

/** Lazy route helper: each feature page is its own chunk (all precached for offline). */
function page(load: () => Promise<{ default: React.ComponentType }>): Pick<RouteObject, "lazy"> {
  return { lazy: async () => ({ Component: (await load()).default }) };
}

const demoRoutes: RouteObject[] = [
  { path: "/interpreter", ...page(() => import("@/features/interpreter/InterpreterPage")), errorElement: <RouteError />, hydrateFallbackElement: loading },
  { path: "/demo/founder-arrival", ...page(() => import("@/features/demo/HeroDemoPage")), errorElement: <RouteError />, hydrateFallbackElement: loading },
  ...Object.entries({ "/home": 9, "/plan": 9, "/documents": 1, "/approvals": 1, "/knowledge/me": 2, "/twin": 2, "/knowledge/governance": 3, "/services": 3, "/agents": 4, "/journey": 5, "/discover": 7, "/simulate": 8, "/what-if": 8, "/assistant": 0 }).map(([path, scene]) => ({ path, element: <Navigate to={`/demo/founder-arrival?scene=${scene}`} replace /> })),
  { path: "*", element: <Navigate to="/demo/founder-arrival" replace /> },
];

export const router = createBrowserRouter(config.demoMode ? demoRoutes : [
  // Independent interpreter has no assistant dock or conversational workflow.
  { path: "/interpreter", ...page(() => import("@/features/interpreter/InterpreterPage")), errorElement: <RouteError />, hydrateFallbackElement: loading },
  { path: "/", element: <RootRedirect />, errorElement: <RouteError /> },
  { path: "/onboarding", ...page(() => import("@/features/onboarding/OnboardingPage")), errorElement: <RouteError />, hydrateFallbackElement: loading },
  {
    element: <AppShell />,
    errorElement: <RouteError />,
    hydrateFallbackElement: loading,
    children: [
      { path: "home", ...page(() => import("@/features/home/HomePage")) },
      { path: "journey", handle: { layout: "full" }, ...page(() => import("@/features/journey/JourneyPage")) },
      {
        path: "knowledge",
        handle: { layout: "full" },
        ...page(() => import("@/features/knowledge/KnowledgeLayout")),
        children: [
          { index: true, element: <Navigate to="governance" replace /> },
          { path: "governance", ...page(() => import("@/features/knowledge/GovernanceGraphPage")) },
          { path: "me", ...page(() => import("@/features/knowledge/TwinGraphPage")) },
        ],
      },
      { path: "agents", handle: { layout: "full" }, ...page(() => import("@/features/agents/AgentsPage")) },
      { path: "documents", handle: { layout: "wide" }, ...page(() => import("@/features/documents/DocumentsPage")) },
      { path: "approvals", handle: { layout: "wide" }, ...page(() => import("@/features/approvals/ApprovalsPage")) },
      { path: "discover", handle: { layout: "wide" }, ...page(() => import("@/features/discover/DiscoverPage")) },
      { path: "simulate", handle: { layout: "wide" }, ...page(() => import("@/features/simulate/SimulatePage")) },
      { path: "assistant", handle: { layout: "full" }, ...page(() => import("@/features/assistant/AssistantPage")) },
      { path: "profile", ...page(() => import("@/features/profile/ProfilePage")) },
      { path: "settings", ...page(() => import("@/features/settings/SettingsPage")) },
      // Scripted demo runs of the real pipeline (shown when the API offers them).
      { path: "demo", element: <Navigate to="/demo/founder-arrival" replace /> },
      { path: "demo/founder-arrival", handle: { layout: "wide" }, ...page(() => import("@/features/demo/FounderArrivalPage")) },
      // Earlier paths, kept so old links and installed shortcuts still work.
      { path: "today", element: <Navigate to="/home" replace /> },
      { path: "twin", element: <Navigate to="/knowledge/me" replace /> },
      { path: "services", element: <Navigate to="/knowledge/governance" replace /> },
      { path: "what-if", element: <Navigate to="/simulate" replace /> },
      { path: "activity", element: <Navigate to="/agents" replace /> },
      { path: "plan", element: <Navigate to="/home" replace /> },
      { path: "*", element: <NotFound /> },
    ],
  },
]);
