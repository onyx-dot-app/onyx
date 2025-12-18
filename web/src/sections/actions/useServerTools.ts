import useSWR, { KeyedMutator } from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { getActionIcon } from "@/lib/tools/mcpUtils";
import { MCPServer, MCPTool, ToolSnapshot } from "@/lib/tools/interfaces";

interface UseServerToolsOptions {
  serverId: number;
  server: MCPServer;
  isExpanded: boolean;
}

interface UseServerToolsReturn {
  tools: MCPTool[];
  isLoading: boolean;
  error: Error | undefined;
  mutate: KeyedMutator<ToolSnapshot[]>;
}

/**
 * Custom hook to lazily load tools for a specific MCP server
 * Only fetches when isExpanded is true
 */
export function useServerTools({
  serverId,
  server,
  isExpanded,
}: UseServerToolsOptions): UseServerToolsReturn {
  const shouldFetch = isExpanded;

  const {
    data: toolsData,
    isLoading,
    error,
    mutate,
  } = useSWR<ToolSnapshot[]>(
    shouldFetch
      ? `/api/admin/mcp/server/${serverId}/tools/snapshots?source=db`
      : null,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
    }
  );

  // Convert ToolSnapshot[] to Tool[] format
  const tools: MCPTool[] = toolsData
    ? toolsData.map((tool) => ({
        id: tool.id.toString(),
        icon: getActionIcon(server.server_url, server.name),
        name: tool.display_name || tool.name,
        description: tool.description,
        isAvailable: true,
        isEnabled: tool.enabled,
      }))
    : [];

  return {
    tools,
    isLoading: isLoading && shouldFetch,
    error,
    mutate,
  };
}
