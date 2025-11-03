import { useMemo } from "react";
import useSWR from "swr";
import { FederatedConnectorOAuthStatus } from "@/components/chat/FederatedOAuthModal";
import { errorHandlingFetcher } from "@/lib/fetcher";

export function useFederatedOAuthStatus() {
  const { data, error, mutate } = useSWR<FederatedConnectorOAuthStatus[]>(
    "/api/federated/oauth-status",
    errorHandlingFetcher
  );

  const connectors = data ?? [];
  const needsAuth = useMemo(
    () => connectors.filter((c) => !c.has_oauth_token),
    [connectors]
  );
  const hasUnauthenticatedConnectors = needsAuth.length > 0;

  return {
    connectors,
    needsAuth,
    hasUnauthenticatedConnectors,
    loading: !error && !data,
    error,
    refetch: mutate,
  };
}
