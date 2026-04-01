"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
<<<<<<< HEAD:web/src/hooks/useHookSpecs.ts
import { HookPointMeta } from "@/refresh-pages/admin/HooksPage/interfaces";
import { SWR_KEYS } from "@/lib/swr-keys";
=======
import { HookPointMeta } from "@/ee/refresh-pages/admin/HooksPage/interfaces";
>>>>>>> 39a3ee1a0 (feat(hook) frontend ee):web/src/ee/hooks/useHookSpecs.ts

export function useHookSpecs() {
  const { data, isLoading, error } = useSWR<HookPointMeta[]>(
    SWR_KEYS.hookSpecs,
    errorHandlingFetcher,
    { revalidateOnFocus: false }
  );

  return { specs: data, isLoading, error };
}
