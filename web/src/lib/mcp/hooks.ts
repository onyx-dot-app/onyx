"use client";

import useSWR, { KeyedMutator, mutate } from "swr";
import { useMemo } from "react";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { getActionIcon } from "@/lib/tools/utils";
import type {
  AgentEditorMCPServer,
  MCPServer,
  MCPServersResponse,
  MCPTool,
} from "@/lib/mcp/types";
import type { ToolSnapshot } from "@/lib/tools/types";

/**
 * Every MCP server the current user can reach.
 *
 * This is the user-facing listing. For the admin console's view of every
 * configured server, including ones this user cannot use, see
 * {@link useAdminMcpServers} — the two return the same shape from different
 * endpoints, so picking the wrong one type-checks and silently answers a
 * different question.
 */
export function useMcpServers() {
  const {
    data: mcpData,
    error,
    isLoading,
    mutate: mutateMcpServers,
  } = useSWR<MCPServersResponse>(SWR_KEYS.mcpServers, errorHandlingFetcher);

  return {
    mcpData: mcpData ?? null,
    isLoading,
    error,
    mutateMcpServers,
  };
}

/**
 * Every configured MCP server, from the admin endpoint. Use this only on admin
 * surfaces; {@link useMcpServers} is what user-facing UI should read.
 */
export function useAdminMcpServers() {
  const {
    data: mcpData,
    error,
    isLoading,
    mutate: mutateMcpServers,
  } = useSWR<MCPServersResponse>(
    SWR_KEYS.adminMcpServers,
    errorHandlingFetcher
  );

  return {
    mcpData: mcpData ?? null,
    isLoading,
    error,
    mutateMcpServers,
  };
}

/**
 * The MCP servers relevant to one agent: those the user can reach, plus any
 * already attached to the agent that they cannot. `can_attach` distinguishes
 * them, so the editor can show an attached server without offering it as a
 * choice the user is not allowed to make.
 */
export function useMcpServersForAgent(agentId: number | undefined) {
  const accessible = useMcpServers();
  const {
    data: attachedData,
    error: attachedError,
    isLoading: attachedIsLoading,
  } = useSWR<MCPServersResponse>(
    agentId ? SWR_KEYS.agentMcpServers(agentId) : null,
    errorHandlingFetcher
  );

  const mcpServers = useMemo<AgentEditorMCPServer[]>(() => {
    const accessibleServers = accessible.mcpData?.mcp_servers ?? [];
    const accessibleIds = new Set(accessibleServers.map((server) => server.id));
    return [
      ...accessibleServers.map((server) => ({ ...server, can_attach: true })),
      ...(attachedData?.mcp_servers ?? [])
        .filter((server) => !accessibleIds.has(server.id))
        .map((server) => ({ ...server, can_attach: false })),
    ];
  }, [accessible.mcpData, attachedData]);

  return {
    mcpServers,
    isLoading:
      accessible.isLoading || (agentId !== undefined && attachedIsLoading),
    error: accessible.error || attachedError,
  };
}

/**
 * MCP servers an admin made available to Craft, with this user's connection
 * state (`craft_connected`).
 */
export function useCraftMcpServers(enabled: boolean = true) {
  const { data, error, isLoading } = useSWR<MCPServersResponse>(
    enabled ? SWR_KEYS.mcpServersCraft : null,
    errorHandlingFetcher,
    // The Apps page re-reads this after every connect/disconnect; holding the
    // previous list keeps the tab from flashing empty on revalidation.
    { keepPreviousData: true }
  );

  const refresh = () => mutate(SWR_KEYS.mcpServersCraft);

  return { data, error, isLoading, refresh };
}

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
export function useServerTools(
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
    shouldFetch ? SWR_KEYS.adminMcpServerToolSnapshots(server.id) : null,
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
        permissions: tool.permissions,
      }))
    : [];

  return {
    tools,
    isLoading: isLoading && shouldFetch,
    error,
    mutate,
  };
}
