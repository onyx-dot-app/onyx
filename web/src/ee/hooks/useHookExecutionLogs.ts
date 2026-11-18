import useSWR from "swr";
import { fetchExecutionLogs } from "@/ee/views/admin/HooksPage/svc";
import type { HookExecutionRecord } from "@/ee/views/admin/HooksPage/interfaces";

const ONE_HOUR_MS = 60 * 60 * 1000;
const THIRTY_DAYS_MS = 30 * 24 * 60 * 60 * 1000;

interface UseHookExecutionLogsResult {
  isLoading: boolean;
  error: Error | undefined;
  hasRecentErrors: boolean;
  recentErrors: HookExecutionRecord[];
  olderErrors: HookExecutionRecord[];
}

export function useHookExecutionLogs(
  hookId: number,
  limit = 10
): UseHookExecutionLogsResult {
  const { data, isLoading, error } = useSWR(
    ["hook-execution-logs", hookId, limit],
    async () => ({
      logs: await fetchExecutionLogs(hookId, limit),
      fetchedAt: Date.now(),
    }),
    { refreshInterval: 60_000 }
  );

  const now = data?.fetchedAt ?? 0;

  const recentErrors =
    data?.logs.filter(
      (log) => now - new Date(log.created_at).getTime() < ONE_HOUR_MS
    ) ?? [];

  const olderErrors =
    data?.logs.filter((log) => {
      const age = now - new Date(log.created_at).getTime();
      return age >= ONE_HOUR_MS && age < THIRTY_DAYS_MS;
    }) ?? [];

  const hasRecentErrors = recentErrors.length > 0;

  return { isLoading, error, hasRecentErrors, recentErrors, olderErrors };
}
