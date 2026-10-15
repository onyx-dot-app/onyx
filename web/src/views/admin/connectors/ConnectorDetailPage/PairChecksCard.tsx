"use client";

import { useTranslations } from "next-intl";
import { toast } from "@opal/layouts";
import type { ValidSources } from "@/lib/connectors/types/source";
import { useCredentialCheckReports } from "@/lib/credentials/hooks";
import type { CredentialCheckRunStatus } from "@/lib/credentials/types";
import type { ConnectorChecksStatus } from "@/lib/connectors/checks/types";
import { NO_CHECKS } from "@/lib/connectors/checks/hooks";
import { CheckCardView } from "@/views/admin/connectors/AddConnectorPage/components/CredentialChecksCard";

// The card reads only whether a run is going or broke. A stored report is
// otherwise complete, and its results say what failed.
const RUN_STATUS: Record<CredentialCheckRunStatus, ConnectorChecksStatus> = {
  running: "running",
  completed: "passed",
  failed_to_run: "failedToRun",
};

export interface PairChecksCardProps {
  source: ValidSources;
  credentialId: number;
  connectorId: number;
  /** Each increment opens the card and scrolls it into view. */
  expandRequest?: number;
}

/** The pair's stored checks: its own report, else the credential's. Nothing shows until one exists. */
export default function PairChecksCard({
  source,
  credentialId,
  connectorId,
  expandRequest = 0,
}: PairChecksCardProps) {
  const t = useTranslations("admin.connectorsList.add.account");
  const { reportFor, rerun } = useCredentialCheckReports(source);
  const report =
    reportFor(credentialId, connectorId) ?? reportFor(credentialId);
  if (report === null) return null;

  const results = report.report?.check_results ?? [];
  const stateCounts = { ...NO_CHECKS };
  for (const result of results) stateCounts[result.status] += 1;

  return (
    <CheckCardView
      status={RUN_STATUS[report.run_status]}
      results={results}
      openChecks={[]}
      inProgressCount={0}
      expectedCount={0}
      stateCounts={stateCounts}
      defaultCollapsed
      expandRequest={expandRequest}
      onRerun={() => {
        rerun(credentialId, connectorId).catch(() =>
          toast.error(t("rerunFailed.toast"))
        );
      }}
    />
  );
}
