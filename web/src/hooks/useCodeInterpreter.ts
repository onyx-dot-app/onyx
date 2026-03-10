import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";

const HEALTH_ENDPOINT = "/api/admin/code-interpreter/health";
const STATUS_ENDPOINT = "/api/admin/code-interpreter";

interface CodeInterpreterHealth {
  healthy: boolean;
}

interface CodeInterpreterStatus {
  enabled: boolean;
}

export default function useCodeInterpreter() {
  const {
    data: healthData,
    error: healthError,
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

  return {
    isHealthy: healthData?.healthy ?? false,
    isEnabled: statusData?.enabled ?? false,
    isLoading: isHealthLoading || isStatusLoading,
    error: healthError || statusError,
    refetch,
  };
}
