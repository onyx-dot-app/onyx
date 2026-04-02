"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { HookPointMeta } from "@/ee/refresh-pages/admin/HooksPage/interfaces";
import { SWR_KEYS } from "@/lib/swr-keys";

export function useHookSpecs() {
  const { data, isLoading, error } = useSWR<HookPointMeta[]>(
    SWR_KEYS.hookSpecs,
    errorHandlingFetcher,
    { revalidateOnFocus: false }
  );

  return { specs: data, isLoading, error };
}
