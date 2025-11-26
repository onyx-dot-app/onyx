import useSWR from "swr";
import { ToolSnapshot } from "@/lib/tools/interfaces";
import { errorHandlingFetcher } from "@/lib/fetcher";

export function useAvailableTools() {
  const { data, error, mutate } = useSWR<ToolSnapshot[]>(
    "/api/tools",
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      dedupingInterval: 60000,
    }
  );

  return {
    tools: data ?? [],
    isLoading: !error && !data,
    error,
    refresh: mutate,
  };
}
