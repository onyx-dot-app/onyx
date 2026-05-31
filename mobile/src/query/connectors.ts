// Connector query hooks (available sources for the current chat).
//
// Replicates web's available-source set from CC-pairs + federated connectors.
// Both endpoints are non-admin:
//   - GET /manage/connector-status (current_chat_accessible_user) -> BasicCCPairInfo[]
//   - GET /federated (BASIC_ACCESS)                               -> FederatedConnectorStatus[]
// useAvailableSourceStrings merges both into a single list of raw source strings.
import { useQuery } from "@tanstack/react-query";
import { errorHandlingFetcher } from "@/lib/api";
import { queryKeys } from "./keys";
import { clientConfig } from "./client";

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
  return useQuery({
    queryKey: [queryKeys.connectorStatus],
    queryFn: () =>
      errorHandlingFetcher<BasicCCPairInfo[]>(
        queryKeys.connectorStatus,
        clientConfig
      ),
    staleTime: 30_000,
  });
}

export function useFederatedConnectors() {
  return useQuery({
    queryKey: [queryKeys.federatedConnectors],
    queryFn: () =>
      errorHandlingFetcher<FederatedConnectorStatus[]>(
        queryKeys.federatedConnectors,
        clientConfig
      ),
    staleTime: 30_000,
  });
}

/** Combined raw source strings for the current chat (CC-pairs + federated). */
export function useAvailableSourceStrings(): string[] {
  const { data: ccPairs } = useConnectorStatus();
  const { data: federated } = useFederatedConnectors();
  const cc = (ccPairs ?? []).map((p) => p.source);
  const fed = (federated ?? []).map((f) => f.source);
  return [...cc, ...fed];
}
