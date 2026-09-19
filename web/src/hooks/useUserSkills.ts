"use client";

import useSWR from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";
import type { SkillsList } from "@/lib/skills/types";

export default function useUserSkills() {
  const { data, error, isLoading, mutate } = useSWR<SkillsList>(
    SWR_KEYS.userSkills,
    errorHandlingFetcher
  );

  return { data, error, isLoading, refresh: mutate };
}
