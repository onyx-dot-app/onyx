"use client";

import useSWR, { mutate } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";
import type { SkillsList } from "@/refresh-pages/admin/SkillsPage/interfaces";

export default function useAdminSkills() {
  const { data, error, isLoading } = useSWR<SkillsList>(
    SWR_KEYS.adminSkills,
    errorHandlingFetcher
  );

  const refresh = () => mutate(SWR_KEYS.adminSkills);

  return { data, error, isLoading, refresh };
}
