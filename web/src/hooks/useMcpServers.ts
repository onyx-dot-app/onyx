"use client";

import { errorHandlingFetcher } from "@/lib/fetcher";
import { MCPServersResponse } from "@/lib/tools/interfaces";
import useSWR from "swr";

/**
 * Fetches MCP (Model Context Protocol) servers configuration.
 *
 * MCP servers provide additional tools and capabilities to agents through
 * the Model Context Protocol. This hook polls the MCP servers endpoint
 * every 10 seconds to keep the data fresh.
 *
 * @returns Object containing:
 *   - mcpData: MCPServersResponse data or null if not loaded
 *   - isLoading: Boolean indicating if data is being fetched
 *   - error: Any error that occurred during fetch
 *   - mutateMcpServers: Function to manually revalidate the data
 *
 * @example
 * const { mcpData, isLoading } = useMcpServers();
 * if (isLoading) return <Spinner />;
 * return <MCPServersList servers={mcpData} />;
 */
export default function useMcpServers() {
  const {
    data: mcpData,
    error,
    isLoading: isMcpLoading,
    mutate: mutateMcpServers,
  } = useSWR<MCPServersResponse>(
    "/api/admin/mcp/servers",
    errorHandlingFetcher,
    { refreshInterval: 10000 }
  );

  return {
    mcpData: mcpData ?? null,
    isLoading: isMcpLoading,
    error,
    mutateMcpServers,
  };
}
