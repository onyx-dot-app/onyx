import { useState, useEffect } from "react";
import { FederatedConnectorOAuthStatus } from "@/components/chat/FederatedOAuthModal";

export function useFederatedOAuthStatus() {
  const [connectors, setConnectors] = useState<FederatedConnectorOAuthStatus[]>(
    []
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchOAuthStatus = async () => {
    try {
      setLoading(true);
      const response = await fetch("/api/federated/oauth-status");

      if (!response.ok) {
        throw new Error("Failed to fetch OAuth status");
      }

      const data = await response.json();
      setConnectors(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "An error occurred");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchOAuthStatus();
  }, []);

  const needsAuth = connectors.filter((c) => !c.has_oauth_token);
  const hasUnauthenticatedConnectors = needsAuth.length > 0;

  return {
    connectors,
    needsAuth,
    hasUnauthenticatedConnectors,
    loading,
    error,
    refetch: fetchOAuthStatus,
  };
}
