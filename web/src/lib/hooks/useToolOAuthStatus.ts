import { useState, useEffect, useCallback } from "react";
import { getOAuthTokenStatus, initiateOAuthFlow } from "@/lib/oauth/api";
import { OAuthTokenStatus, ToolSnapshot } from "@/lib/tools/interfaces";

interface ToolOAuthStatus {
  has_token: boolean;
  is_expired: boolean;
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
      const statuses = await getOAuthTokenStatus();
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
  const getOAuthStatusForTool = useCallback(
    (tool: ToolSnapshot): ToolOAuthStatus | undefined => {
      if (!tool.oauth_config_id) return undefined;

      const status = oauthTokenStatuses.find(
        (s) => s.oauth_config_id === tool.oauth_config_id
      );

      if (!status) return undefined;

      return {
        has_token: status.has_token,
        is_expired: status.is_expired,
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
   * Check if a tool needs authentication
   */
  const needsAuthentication = useCallback(
    (tool: ToolSnapshot): boolean => {
      const status = getOAuthStatusForTool(tool);
      if (!status) return false;
      return !status.has_token || status.is_expired;
    },
    [getOAuthStatusForTool]
  );

  /**
   * Get all tools that need authentication from a list
   */
  const getToolsNeedingAuth = useCallback(
    (tools: ToolSnapshot[]): ToolSnapshot[] => {
      return tools.filter((tool) => needsAuthentication(tool));
    },
    [needsAuthentication]
  );

  return {
    oauthTokenStatuses,
    loading,
    error,
    getOAuthStatusForTool,
    authenticateTool,
    needsAuthentication,
    getToolsNeedingAuth,
    refetch: fetchOAuthStatus,
  };
}
