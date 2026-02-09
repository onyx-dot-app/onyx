"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { MinimalUserSnapshot } from "@/lib/types";

export default function useShareableUsers() {
  const { data, error, mutate, isLoading } = useSWR<MinimalUserSnapshot[]>(
    "/api/users",
    errorHandlingFetcher
  );

  return {
    data,
    isLoading,
    error,
    refreshShareableUsers: mutate,
  };
}
