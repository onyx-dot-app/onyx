"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { HookPointMeta } from "@/app/admin/hooks/interfaces";

export function useHookSpecs() {
  const { data, isLoading, error } = useSWR<HookPointMeta[]>(
    "/api/admin/hooks/specs",
    errorHandlingFetcher,
    { revalidateOnFocus: false }
  );

  return { specs: data, isLoading, error };
}
