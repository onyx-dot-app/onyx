"use client";

import { useCapabilityReport } from "@/lib/connectors/checks/hooks";
import { ConnectorsCheckCard } from "@/sections/cards/ConnectorsCheckCard";

interface ConnectorsCheckSectionProps {
  credentialId: number;
  connectorId: number;
}

/**
 * The checks card for one connector-credential pair, fed by the stored
 * capability report. Hidden when the report cannot be fetched, so a
 * permissions or network problem never masquerades as "no checks yet".
 */
export function ConnectorsCheckSection({
  credentialId,
  connectorId,
}: ConnectorsCheckSectionProps) {
  const { snapshot, isLoading, error, running, rerun } = useCapabilityReport(
    credentialId,
    connectorId
  );
  if (error) return null;

  return (
    <ConnectorsCheckCard
      snapshot={snapshot ?? null}
      loading={isLoading}
      running={running}
      onRerun={() => void rerun()}
    />
  );
}
