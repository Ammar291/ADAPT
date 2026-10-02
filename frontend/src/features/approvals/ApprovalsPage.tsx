import { tr, useLocale } from "@/i18n";
/**
 * Approvals: actions ADAPT prepared for the journey (official portal handoffs, details it
 * would share, bookings) that wait for the user's OK, and what happened after approving.
 * Drafted documents are approved in Documents; this page is only for actions.
 */
import { PageHeader } from "@/components/ui/PageHeader";
import { ApprovalsTab } from "@/features/documents/components/ApprovalsTab";

export default function ApprovalsPage() {
  useLocale();
  return (
    <div className="flex flex-col">
      <PageHeader
        title={tr("copy.approvals_deb9d03")}
        description={tr("copy.when_adapt_prepares_something_that_shares_your_d_6b598be")}
      />
      <ApprovalsTab />
    </div>
  );
}
