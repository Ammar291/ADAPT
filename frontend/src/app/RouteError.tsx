import { tr, useLocale } from "@/i18n";
import { isRouteErrorResponse, Link, useRouteError } from "react-router";
import { Compass } from "lucide-react";
import { BrandMark } from "./layout/BrandMark";
import { buttonClass } from "@/components/ui/Button";
import { ErrorState } from "@/components/ui/States";
import { config } from "@/lib/config";

export function RouteError() {
  useLocale();
  const error = useRouteError();

  if (config.demoMode) return <div className="mx-auto flex min-h-dvh max-w-lg flex-col justify-center p-6"><BrandMark className="mb-6 size-11" /><h1 className="text-2xl">{tr("copy.your_demo_plan_is_saved_ad706a6")}</h1><p className="mt-3 text-muted">{tr("copy.this_chapter_couldn_t_open_reload_to_continue_fr_68c1e50")}</p><a href="/demo/founder-arrival" className={buttonClass("primary", "md", "mt-6 self-start")}>{tr("copy.continue_the_demo_ed1e9ae")}</a></div>;

  if (isRouteErrorResponse(error) && error.status === 404) {
    return (
      <div className="mx-auto max-w-lg p-6 pt-16">
        <NotFound />
      </div>
    );
  }
  return (
    <div className="mx-auto flex min-h-dvh max-w-lg flex-col justify-center p-6">
      <BrandMark className="mb-6 size-11" />
      <h1 className="mb-5 text-2xl">{tr("copy.we_couldn_t_open_this_page_2100ac9")}</h1>
      <ErrorState error={error} onRetry={() => window.location.reload()} />
      <Link to="/home" className={buttonClass("ghost", "md", "mt-4 self-start")}>{tr("copy.return_to_your_workspace_f05b324")}</Link>
    </div>
  );
}

export function NotFound() {
  useLocale();
  return (
    <div className="max-w-lg pt-10">
      <span className="mb-5 flex size-14 items-center justify-center rounded-2xl bg-primary-tint text-primary"><Compass className="size-6" aria-hidden /></span>
      <h1 className="text-2xl">{tr("copy.page_not_found_bc3023b")}</h1>
      <p className="mt-2 text-muted">{tr("copy.the_link_may_be_out_of_date_your_plan_is_still_w_73468e1")}</p>
      <Link to="/home" className={buttonClass("primary", "md", "mt-6")}>
        {tr("copy.go_to_home_c05b389")}</Link>
    </div>
  );
}
