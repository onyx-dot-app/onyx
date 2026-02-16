"use client";

import { errorHandlingFetcher } from "@/lib/fetcher";
import { MCPServersResponse } from "@/lib/tools/interfaces";
import useSWR from "swr";

/**
 * Fetch MCP servers for non-admin UIs (e.g. agent editor).
 *
 * This endpoint is available to all authenticated users so basic users can
 * attach MCP actions to assistants.
 */
export default function useMcpServersForAgentEditor() {
  const {
    data: mcpData,
    error,
    isLoading: isMcpLoading,
    mutate: mutateMcpServers,
  } = useSWR<MCPServersResponse>("/api/mcp/servers", errorHandlingFetcher);

  return {
    mcpData: mcpData ?? null,
    isLoading: isMcpLoading,
    error,
    mutateMcpServers,
  };
}
