"use client";

import useSWR from "swr";
import { Project } from "@/lib/projects/types";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";

export function useProjects() {
  const { data, error, mutate } = useSWR<Project[]>(
    SWR_KEYS.userProjects,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      revalidateIfStale: false,
      dedupingInterval: 30000,
    }
  );

  return {
    projects: data ?? [],
    isLoading: !error && !data,
    error,
    refreshProjects: mutate,
  };
}
