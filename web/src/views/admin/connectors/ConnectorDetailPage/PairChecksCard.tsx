"use client";

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
  /** The pair's first index attempt waits on its checks. */
  held: boolean;
  /** Each increment opens the card and scrolls it into view. */
  expandRequest?: number;
}

/**
 * The pair's stored checks: its own report, else the credential's. It shows
 * only while the checks run or hold the pair, open while they run.
 */
export default function PairChecksCard({
  source,
  credentialId,
  connectorId,
  held,
  expandRequest = 0,
}: PairChecksCardProps) {
  const { reportFor } = useCredentialCheckReports(source);
  const report =
    reportFor(credentialId, connectorId) ?? reportFor(credentialId);
  const running: boolean = report?.run_status === "running";
  if (report === null || (!held && !running)) return null;

  const progress = running ? report.progress : null;
  const results = progress?.check_results ?? report.report?.check_results ?? [];
  const openChecks = progress?.open_checks ?? [];
  const stateCounts = { ...NO_CHECKS };
  for (const result of results) stateCounts[result.status] += 1;
  for (const check of openChecks) stateCounts[check.state] += 1;

  return (
    <CheckCardView
      // Remount when a run starts or ends, so the card opens while it runs.
      key={running ? "running" : "settled"}
      status={RUN_STATUS[report.run_status]}
      results={results}
      openChecks={openChecks}
      inProgressCount={stateCounts.running}
      expectedCount={stateCounts.pending}
      stateCounts={stateCounts}
      defaultCollapsed={!running}
      expandRequest={expandRequest}
    />
  );
}
