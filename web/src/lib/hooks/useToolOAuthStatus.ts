import { useState, useEffect, useCallback } from "react";
import { getUserOAuthTokenStatus, initiateOAuthFlow } from "@/lib/oauth/api";
import { OAuthTokenStatus, ToolSnapshot } from "@/lib/tools/interfaces";

export interface ToolAuthStatus {
  // whether or not the user has EVER auth'd
  hasToken: boolean;
  // whether or not the user's current token is expired
  isTokenExpired: boolean;
}

export function useToolOAuthStatus(assistantId?: number) {
  const [oauthTokenStatuses, setOauthTokenStatuses] = useState<
    OAuthTokenStatus[]
  >([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchOAuthStatus = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const statuses = await getUserOAuthTokenStatus();
      setOauthTokenStatuses(statuses);
    } catch (err) {
      console.error("Error fetching OAuth token statuses:", err);
      setError(err instanceof Error ? err.message : "An error occurred");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchOAuthStatus();
  }, [assistantId, fetchOAuthStatus]);

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
    refetch: fetchOAuthStatus,
  };
}
