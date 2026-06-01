// Available sources for the current chat: web's CC-pair + federated set, merged
// by useAvailableSourceStrings. Both endpoints are non-admin.
import { useMemo } from "react";
import { queryKeys } from "./keys";
import { useSimpleQuery } from "./client";

export interface BasicCCPairInfo {
  has_successful_run: boolean;
  source: string;
  status: string;
}

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
