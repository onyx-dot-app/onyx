import { useCallback, useEffect, useRef } from "react";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { initiateOAuthFlow } from "@/lib/oauth/api";
import { OAuthTokenStatus, ToolSnapshot } from "@/lib/tools/interfaces";

export interface ToolAuthStatus {
  // whether or not the user has EVER auth'd
  hasToken: boolean;
  // whether or not the user's current token is expired
  isTokenExpired: boolean;
}

export function useToolOAuthStatus(agentId?: number) {
  const {
    data: oauthTokenStatuses = [],
    isLoading: loading,
    error: swrError,
    mutate,
  } = useSWR<OAuthTokenStatus[]>(
    "/api/user-oauth-token/status",
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      dedupingInterval: 60_000,
    }
  );

  const error: string | null = swrError
    ? swrError instanceof Error
      ? swrError.message
      : "An error occurred"
    : null;

  // Re-validate when the active agent changes so the UI reflects fresh token
  // state for the new agent's tools without waiting for the dedup interval.
  const prevAgentIdRef = useRef(agentId);
  useEffect(() => {
    if (prevAgentIdRef.current !== agentId) {
      prevAgentIdRef.current = agentId;
      mutate();
    }
  }, [agentId, mutate]);

  /**
   * Get OAuth status for a specific tool
   */
  const getToolAuthStatus = useCallback(
    (tool: ToolSnapshot): ToolAuthStatus | undefined => {
      if (!tool.oauth_config_id) return undefined;

      const status = oauthTokenStatuses.find(
        (s) => s.oauth_config_id === tool.oauth_config_id
      );

      if (!status)
        return {
          hasToken: false,
          isTokenExpired: false,
        };

      return {
        hasToken: true,
        isTokenExpired: status.is_expired,
      };
    },
    [oauthTokenStatuses]
  );

  /**
   * Initiate OAuth authentication flow for a tool
   */
  const authenticateTool = useCallback(
    async (tool: ToolSnapshot): Promise<void> => {
      if (!tool.oauth_config_id) {
        throw new Error("Tool does not have OAuth configuration");
      }

      try {
        await initiateOAuthFlow(
          tool.oauth_config_id,
          window.location.pathname + window.location.search
        );
      } catch (err) {
        console.error("Error initiating OAuth flow:", err);
        throw err;
      }
    },
    []
  );

  /**
   * Get all tools that need authentication from a list
   */
  const getToolsNeedingAuth = useCallback(
    (tools: ToolSnapshot[]): ToolSnapshot[] => {
      return tools.filter((tool) => !getToolAuthStatus(tool));
    },
    [getToolAuthStatus]
  );

  return {
    oauthTokenStatuses,
    loading,
    error,
    getToolAuthStatus,
    authenticateTool,
    getToolsNeedingAuth,
    refetch: () => mutate(),
  };
}
