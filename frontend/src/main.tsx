import { tr } from "@/i18n";
import "@/app/demoSeed"; // must run before the router reads the URL
import "@/styles/index.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router/dom";
import { Providers } from "@/app/providers";
import { router } from "@/app/router";
import { Bootstrap } from "@/app/SessionGate";
import { UpdatePrompt } from "@/app/layout/SystemNotices";
import { config } from "@/lib/config";

const root = document.getElementById("root");
if (!root) throw new Error(tr("copy.missing_root_element_c27fa18", { lng: "en" }));

// Explicit interpreter demo can run without the private account/backend bootstrap.
const interpreterDemo = window.location.pathname === "/interpreter" && new URLSearchParams(window.location.search).get("demo") === "1";

createRoot(root).render(
  <StrictMode>
    <Providers>
      <UpdatePrompt />
      {config.demoMode || interpreterDemo ? <RouterProvider router={router} /> : <Bootstrap><RouterProvider router={router} /></Bootstrap>}
    </Providers>
  </StrictMode>,
);
