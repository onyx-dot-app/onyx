"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import type { Skill } from "@/lib/skills/types";
import { SWR_KEYS } from "@/lib/swr-keys";

export function usePluginDetail(pluginId: string | null, fallback?: Skill) {
  const { data, error, isLoading, mutate } = useSWR<Skill, Error>(
    pluginId ? SWR_KEYS.userSkill(pluginId) : null,
    errorHandlingFetcher,
    { fallbackData: fallback }
  );
  return { data, error, isLoading, refresh: mutate };
}
