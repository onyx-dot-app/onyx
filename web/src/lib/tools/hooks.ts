"use client";

import useSWR, { mutate } from "swr";
import { create } from "zustand";
import { useEffect, useMemo, useRef } from "react";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";
import type {
  AgentEditorMCPServer,
  MCPServersResponse,
  ToolSnapshot,
} from "@/lib/tools/types";
import { useActiveAgent } from "@/lib/agents/hooks";
import { useActiveProject } from "@/lib/projects/hooks";
import useChatSessions from "@/hooks/useChatSessions";

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

interface ForcedToolState {
  forcedToolId: number | null;
  toggleForcedTool: (id: number) => void;
  clearForcedTool: () => void;
}

/**
 * The tool the next message will be made to use, if any.
 *
 * A forced tool runs whether or not the model would have chosen it. Only one
 * can be forced at a time — the request carries a single `forced_tool_id` —
 * so the state is that one id rather than a list that callers must keep to
 * one entry by convention.
 *
 * Local UI state, so a module-level store: every caller wants the same value
 * and none of them thread it.
 */
export const useForcedTools = create<ForcedToolState>(function (set, get) {
  return {
    forcedToolId: null,

    // Clicking the tool that is already forced unforces it; clicking any other
    // replaces it, since forcing two is not a state that can be sent.
    toggleForcedTool: (id) =>
      set({ forcedToolId: get().forcedToolId === id ? null : id }),

    clearForcedTool: () => set({ forcedToolId: null }),
  };
});

/**
 * Drops the forced tool when the conversation it was meant for goes away.
 *
 * A forced tool is a choice about the next message, so it should not outlive
 * the context that choice was made in: switching agent, switching project, or
 * moving to a different chat all leave it meaningless.
 *
 * One exception, and it is the common path rather than an edge case. Sending
 * the first message is what creates the chat, so the session id goes from null
 * to an id on the way out — clearing there would discard the tool the user
 * forced by the very act of using it. That is a chat appearing, not a chat
 * being left, so it does not reset.
 *
 * Mount this once per chat surface, above whatever renders the tools popover.
 * The popover itself is rendered only when there is an agent, which is the
 * wrong lifetime for a rule about losing one.
 */
export function useToolsController() {
  const agent = useActiveAgent();
  const { currentChatSessionId } = useChatSessions();
  const activeProject = useActiveProject();
  const { clearForcedTool } = useForcedTools();

  const priorSessionIdRef = useRef(currentChatSessionId);

  useEffect(() => {
    const priorSessionId = priorSessionIdRef.current;
    priorSessionIdRef.current = currentChatSessionId;

    // The user's own send created this chat; the tool is for the message
    // already on its way.
    if (priorSessionId === null && currentChatSessionId !== null) return;

    clearForcedTool();
  }, [agent?.id, currentChatSessionId, activeProject?.id, clearForcedTool]);
}

/**
 * Hook to fetch all available tools from the backend.
 *
 * This hook fetches the complete list of tools that can be used with agents,
 * including built-in tools (SearchTool, ImageGenerationTool, WebSearchTool, PythonTool)
 * and any dynamically configured tools (MCP servers, OpenAPI tools).
 *
 * @example
 * ```tsx
 * const { tools, isLoading, error, refresh } = useAvailableTools();
 *
 * if (isLoading) return <Loading />;
 * if (error) return <Error />;
 *
 * const imageGenTool = tools.find(t => t.in_code_tool_id === "ImageGenerationTool");
 * const isImageGenAvailable = !!imageGenTool;
 * ```
 */
export function useAvailableTools() {
  const { data, isLoading, error, mutate } = useSWR<ToolSnapshot[]>(
    SWR_KEYS.tools,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      revalidateIfStale: false,
      dedupingInterval: 60000,
    }
  );

  return {
    tools: data ?? [],
    isLoading,
    error,
    refresh: mutate,
  };
}
