import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";

const HEALTH_ENDPOINT = "/api/admin/code-interpreter/health";
const STATUS_ENDPOINT = "/api/admin/code-interpreter";

export type CodeInterpreterHealthStatus =
  | "healthy"
  | "unhealthy"
  | "connection_lost";

interface CodeInterpreterHealth {
  connected: boolean;
  error: string;
}

interface CodeInterpreterStatus {
  enabled: boolean;
}

export default function useCodeInterpreter() {
  const {
    data: healthData,
    error: healthFetchError,
    isLoading: isHealthLoading,
    mutate: refetchHealth,
  } = useSWR<CodeInterpreterHealth>(HEALTH_ENDPOINT, errorHandlingFetcher, {
    refreshInterval: 30000,
  });

  const {
    data: statusData,
    error: statusError,
    isLoading: isStatusLoading,
    mutate: refetchStatus,
  } = useSWR<CodeInterpreterStatus>(STATUS_ENDPOINT, errorHandlingFetcher);

  function refetch() {
    refetchHealth();
    refetchStatus();
  }

  const status: CodeInterpreterHealthStatus = healthFetchError
    ? "connection_lost"
    : !healthData?.connected
      ? "connection_lost"
      : healthData.error
        ? "unhealthy"
        : "healthy";

  const error = healthFetchError?.message || healthData?.error || undefined;

  return {
    status: isStatusLoading ? undefined : status,
    error,
    isEnabled: statusData?.enabled ?? false,
    isLoading: isHealthLoading || isStatusLoading,
    fetchError: healthFetchError || statusError,
    refetch,
  };
}
