"use client";

import useSWR, { mutate } from "swr";
import { useMemo } from "react";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { toCraftMcpServers } from "@/lib/integrations/craft";
import type { MemberIntegration } from "@/lib/integrations/types";

/**
 * The MCP integrations of the plugins the user turned on, with the user's
 * connection state (`craft_connected`).
 */
export function useCraftMcpServers(enabled: boolean = true) {
  const { data, error, isLoading } = useSWR<MemberIntegration[]>(
    enabled ? SWR_KEYS.integrations : null,
    errorHandlingFetcher,
    // The Apps page re-reads this after every connect/disconnect; holding the
    // previous list keeps the tab from flashing empty on revalidation.
    { keepPreviousData: true }
  );
  const servers = useMemo(
    () => (data ? toCraftMcpServers(data) : undefined),
    [data]
  );

  const refresh = () => mutate(SWR_KEYS.integrations);

  return { data: servers, error, isLoading, refresh };
}
