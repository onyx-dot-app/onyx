"use client";

import useSWR, { mutate } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";
import type { ExternalAppUserResponse } from "@/app/craft/v1/apps/registry";

export default function useUserExternalApps(enabled: boolean = true) {
  const { data, error, isLoading } = useSWR<ExternalAppUserResponse[]>(
    enabled ? SWR_KEYS.buildExternalApps : null,
    errorHandlingFetcher
  );

  const refresh = () => mutate(SWR_KEYS.buildExternalApps);

  return { data, error, isLoading, refresh };
}
