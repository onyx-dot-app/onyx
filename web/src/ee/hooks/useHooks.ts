"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { HookResponse } from "@/ee/refresh-pages/admin/HooksPage/interfaces";
import { SWR_KEYS } from "@/lib/swr-keys";

export function useHooks() {
  const { data, isLoading, error, mutate } = useSWR<HookResponse[]>(
    SWR_KEYS.hooks,
    errorHandlingFetcher,
    { revalidateOnFocus: false }
  );

  return { hooks: data, isLoading, error, mutate };
}
