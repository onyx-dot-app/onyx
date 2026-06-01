// Connector query hooks (available sources for the current chat).
//
// Replicates web's available-source set from CC-pairs + federated connectors.
// Both endpoints are non-admin:
//   - GET /manage/connector-status (current_chat_accessible_user) -> BasicCCPairInfo[]
//   - GET /federated (BASIC_ACCESS)                               -> FederatedConnectorStatus[]
// useAvailableSourceStrings merges both into a single list of raw source strings.
import { useMemo } from "react";
import { queryKeys } from "./keys";
import { useSimpleQuery } from "./client";

/** Non-admin CC-pair status row (subset of the backend ConnectorIndexingStatus). */
export interface BasicCCPairInfo {
  has_successful_run: boolean;
  source: string;
  status: string;
}

/** Federated connector status row (subset of the backend FederatedConnectorStatus). */
export interface FederatedConnectorStatus {
  id: number;
  source: string;
  name: string;
}

export function useConnectorStatus() {
  return useSimpleQuery<BasicCCPairInfo[]>(queryKeys.connectorStatus);
}

export function useFederatedConnectors() {
  return useSimpleQuery<FederatedConnectorStatus[]>(
    queryKeys.federatedConnectors
  );
}

/** Combined raw source strings for the current chat (CC-pairs + federated). */
export function useAvailableSourceStrings(): string[] {
  const { data: ccPairs } = useConnectorStatus();
  const { data: federated } = useFederatedConnectors();
  return useMemo(
    () => [
      ...(ccPairs ?? []).map((p) => p.source),
      ...(federated ?? []).map((f) => f.source),
    ],
    [ccPairs, federated]
  );
}
