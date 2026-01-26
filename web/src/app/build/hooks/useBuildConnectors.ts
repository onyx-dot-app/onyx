import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import {
  BuildConnectorConfig,
  ConnectorStatus,
} from "@/app/build/v1/configure/components/ConnectorCard";

interface BuildConnectorListResponse {
  connectors: BuildConnectorConfig[];
}

/**
 * Hook to fetch and manage build mode connectors.
 *
 * @returns Object containing:
 * - `connectors`: Array of connector configurations
 * - `hasActiveConnector`: True if at least one connector has status "connected"
 * - `hasAnyConnector`: True if any connectors exist (regardless of status)
 * - `isLoading`: True while fetching
 * - `mutate`: Function to refetch connectors
 */
export function useBuildConnectors() {
  const { data, isLoading, mutate } = useSWR<BuildConnectorListResponse>(
    "/api/build/connectors",
    errorHandlingFetcher,
    { refreshInterval: 30000 } // 30 seconds - matches configure page
  );

  const connectors = data?.connectors ?? [];

  // At least one connector with status "connected" (actively synced)
  const hasActiveConnector = connectors.some((c) => c.status === "connected");

  // Any connector exists (regardless of status)
  const hasAnyConnector = connectors.length > 0;

  return {
    connectors,
    hasActiveConnector,
    hasAnyConnector,
    isLoading,
    mutate,
  };
}
