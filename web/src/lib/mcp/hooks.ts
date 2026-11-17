"use client";

import useSWR, { mutate } from "swr";
import { useMemo } from "react";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { toCraftMcpServers } from "@/lib/integrations/craft";
import type { MemberIntegration } from "@/lib/integrations/types";
import type { AgentEditorMCPServer, MCPServersResponse } from "@/lib/mcp/types";

/**
 * Every MCP server the current user can reach.
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
 * The MCP integrations of the plugins the user turned on, with the user's
 * connection state (`craft_connected`).
 */
export function useCraftMcpServers(enabled: boolean = true) {
  const { data, error, isLoading } = useSWR<MemberIntegration[]>(
    enabled ? SWR_KEYS.integrations : null,
    errorHandlingFetcher,
    // The Apps page re-reads this after every connect/disconnect; holding the
    // previous list keeps the tab from flashing empty on revalidation.
    { keepPreviousData: true }
  );
  const servers = useMemo(
    () => (data ? toCraftMcpServers(data) : undefined),
    [data]
  );

  const refresh = () => mutate(SWR_KEYS.integrations);

  return { data: servers, error, isLoading, refresh };
}
