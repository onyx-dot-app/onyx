import useSWR from "swr";
import { CCPairBasicInfo } from "@/lib/types";
import { errorHandlingFetcher } from "@/lib/fetcher";

export function useCCPairs() {
  const { data, error, mutate } = useSWR<CCPairBasicInfo[]>(
    "/api/manage/connector-status",
    errorHandlingFetcher
  );

  return {
    ccPairs: data,
    isLoading: !error && !data,
    error,
    refetch: mutate,
  };
}
