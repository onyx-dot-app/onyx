"use client";

import useSWR, { mutate } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";
import type { SkillsList } from "@/lib/skills/types";

export default function useUserSkills() {
  const { data, error, isLoading } = useSWR<SkillsList>(
    SWR_KEYS.userSkills,
    errorHandlingFetcher
  );

  const refresh = () => mutate(SWR_KEYS.userSkills);

  return { data, error, isLoading, refresh };
}
