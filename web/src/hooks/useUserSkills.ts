"use client";

import useSWR from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";
import type { SkillsList } from "@/lib/skills/types";

export default function useUserSkills(enabled = true) {
  const { data, error, isLoading, mutate } = useSWR<SkillsList>(
    enabled ? SWR_KEYS.userSkills : null,
    errorHandlingFetcher
  );

  return { data, error, isLoading, refresh: mutate };
}
