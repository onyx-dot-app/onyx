import useSWR from "swr";
import { fetchExecutionLogs } from "@/refresh-pages/admin/HooksPage/svc";
import type { HookExecutionRecord } from "@/refresh-pages/admin/HooksPage/interfaces";

const ONE_HOUR_MS = 60 * 60 * 1000;
const THIRTY_DAYS_MS = 30 * 24 * 60 * 60 * 1000;

interface UseHookExecutionLogsResult {
  isLoading: boolean;
  hasRecentErrors: boolean;
  recentErrors: HookExecutionRecord[];
  olderErrors: HookExecutionRecord[];
}

export function useHookExecutionLogs(
  hookId: number,
  limit = 10
): UseHookExecutionLogsResult {
  const { data, isLoading } = useSWR(
    ["hook-execution-logs", hookId, limit],
    () => fetchExecutionLogs(hookId, limit),
    { refreshInterval: 60_000 }
  );

  const now = Date.now();

  const recentErrors =
    data?.filter(
      (log) => now - new Date(log.created_at).getTime() < ONE_HOUR_MS
    ) ?? [];

  const olderErrors =
    data?.filter((log) => {
      const age = now - new Date(log.created_at).getTime();
      return age >= ONE_HOUR_MS && age < THIRTY_DAYS_MS;
    }) ?? [];

  const hasRecentErrors = recentErrors.length > 0;

  return { isLoading, hasRecentErrors, recentErrors, olderErrors };
}
