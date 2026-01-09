"use client";

import useSWR, { KeyedMutator } from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { getActionIcon } from "@/lib/tools/mcpUtils";
import { MCPServer, MCPTool, ToolSnapshot } from "@/lib/tools/interfaces";

/**
 * Return type for the useServerTools hook
 */
interface UseServerToolsReturn {
  /** Array of tools available for the MCP server, formatted for UI display */
  tools: MCPTool[];

  /** Loading state - true when fetching tools from the API */
  isLoading: boolean;

  /** Error object if the fetch failed, undefined otherwise */
  error: Error | undefined;

  /** SWR mutate function for manually revalidating or updating the tools cache */
  mutate: KeyedMutator<ToolSnapshot[]>;
}

/**
 * useServerTools
 *
 * A custom hook for lazily loading and managing tools for a specific MCP server.
 * This hook only fetches tools when the server is expanded, reducing unnecessary
 * API calls and improving performance.
 *
 * @param server - The MCP server object containing server metadata (id, url, name)
 * @param isExpanded - Boolean flag indicating whether the server card is expanded.
 *                     Tools are only fetched when this is true.
 *
 * @returns An object containing:
 *   - tools: Array of MCPTool objects formatted for UI display
 *   - isLoading: Boolean indicating if tools are currently being fetched
 *   - error: Error object if fetch failed
 *   - mutate: Function to manually revalidate or update the tools cache
 *
 * @example
 * ```tsx
 * function ServerCard({ server }) {
 *   const [isExpanded, setIsExpanded] = useState(false);
 *   const { tools, isLoading, error, mutate } = useServerTools(server, isExpanded);
 *
 *   if (isLoading) return <div>Loading tools...</div>;
 *   if (error) return <div>Failed to load tools</div>;
 *
 *   return (
 *     <div>
 *       <button onClick={() => setIsExpanded(!isExpanded)}>
 *         {isExpanded ? 'Collapse' : 'Expand'}
 *       </button>
 *       {isExpanded && tools.map(tool => (
 *         <ToolItem key={tool.id} {...tool} />
 *       ))}
 *     </div>
 *   );
 * }
 * ```
 *
 * @remarks
 * - Uses SWR for caching and automatic revalidation
 * - Automatically converts ToolSnapshot[] from API to MCPTool[] for UI
 * - Revalidation on focus and reconnect are disabled to reduce API calls
 * - The hook will not fetch if isExpanded is false (lazy loading)
 */
export default function useServerTools(
  server: MCPServer,
  isExpanded: boolean
): UseServerToolsReturn {
  const shouldFetch = isExpanded;

  const {
    data: toolsData,
    isLoading,
    error,
    mutate,
  } = useSWR<ToolSnapshot[]>(
    shouldFetch
      ? `/api/admin/mcp/server/${server.id}/tools/snapshots?source=db`
      : null,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
    }
  );

  // Convert ToolSnapshot[] to MCPTool[] format for UI consumption
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
