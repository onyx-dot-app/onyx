import useSWR from "swr";
import { errorHandlingFetcher, skipRetryOnAuthError } from "@/lib/fetcher";
import type { SandboxStatus } from "@/lib/sandbox-status/types";

export const SANDBOX_STATUS_URL = "/api/admin/sandbox/status";

// Nodes report every 20 seconds.
const REFRESH_INTERVAL_MS = 20_000;

export function useSandboxStatus() {
  return useSWR<SandboxStatus>(SANDBOX_STATUS_URL, errorHandlingFetcher, {
    onErrorRetry: skipRetryOnAuthError,
    refreshInterval: REFRESH_INTERVAL_MS,
    revalidateOnFocus: false,
  });
}
