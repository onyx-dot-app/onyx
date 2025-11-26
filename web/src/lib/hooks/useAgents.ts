import useSWR from "swr";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { errorHandlingFetcher } from "@/lib/fetcher";

export function useAgents() {
  const { data, error, mutate } = useSWR<MinimalPersonaSnapshot[]>(
    "/api/persona",
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      dedupingInterval: 60000,
    }
  );

  return {
    agents: data ?? [],
    isLoading: !error && !data,
    error,
    refresh: mutate,
  };
}

export function usePinnedAgents() {
  const { data, error, mutate } = useSWR<number[]>(
    "/api/user/pinned-assistants",
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      dedupingInterval: 60000,
    }
  );

  return {
    pinnedAgentIds: data ?? [],
    isLoading: !error && !data,
    error,
    refresh: mutate,
  };
}
