"use client";

import { useMemo } from "react";
import useSWR, { mutate } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { toCraftApps } from "@/lib/integrations/craft";
import type { MemberIntegration } from "@/lib/integrations/types";

export default function useUserExternalApps(enabled: boolean = true) {
  const { data, error, isLoading } = useSWR<MemberIntegration[]>(
    enabled ? SWR_KEYS.integrations : null,
    errorHandlingFetcher
  );
  const apps = useMemo(() => (data ? toCraftApps(data) : undefined), [data]);

  const refresh = () => mutate(SWR_KEYS.integrations);

  return { data: apps, error, isLoading, refresh };
}
