"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { HookResponse } from "@/refresh-pages/admin/HooksPage/interfaces";

export function useHooks() {
  const { data, isLoading, error, mutate } = useSWR<HookResponse[]>(
    "/api/admin/hooks",
    errorHandlingFetcher,
    { revalidateOnFocus: false }
  );

  return { hooks: data, isLoading, error, mutate };
}
