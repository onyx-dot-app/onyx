"use client";

import useSWR, { mutate } from "swr";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";
import type {
  AgentEditorMCPServer,
  MCPServersResponse,
  ToolSnapshot,
} from "@/lib/tools/types";
import { createSharedHook } from "@opal/hooks";
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
  /**
   * Called by the send path when a message is about to create the chat it is
   * being sent to. Excuses exactly the next session change from the reset, so
   * the tool survives to the request it was chosen for.
   */
  keepThroughNextSessionChange: () => void;
}

/**
 * The tool the next message will be made to use, if any.
 *
 * A forced tool runs whether or not the model would have chosen it. Only one
 * can be forced at a time — the request carries a single `forced_tool_id` — so
 * the state is that one id rather than a list callers must keep to one entry
 * by convention.
 */
function useForcedToolsState(): ForcedToolState {
  const [forcedToolId, setForcedToolId] = useState<number | null>(null);

  // Clicking the tool that is already forced unforces it; clicking any other
  // replaces it, since forcing two is not a state that can be sent.
  const toggleForcedTool = useCallback(
    (id: number) => setForcedToolId((current) => (current === id ? null : id)),
    []
  );
  const clearForcedTool = useCallback(() => setForcedToolId(null), []);

  // Only the send path can tell "the chat I just created" from "a chat I
  // navigated to" — both read as null -> id from here, and the URL marker the
  // navigation carries is stripped with `history.replaceState`, so it is not
  // reliably visible. So the send path says so instead of this guessing.
  const keepThroughNextSessionChangeRef = useRef(false);
  const keepThroughNextSessionChange = useCallback(() => {
    keepThroughNextSessionChangeRef.current = true;
  }, []);

  // Switching agent, project or chat leaves the choice meaningless, so it does
  // not survive them. The exception is the common path: sending the first
  // message is what creates the chat, so the session id goes null -> id on the
  // way out, and clearing there would discard the tool the user forced by the
  // act of using it. That is a chat appearing, not one being left. The provider
  // is per surface rather than per agent, so an agent switch does not unmount
  // it and this is what handles that case.
  const agent = useActiveAgent();
  const { currentChatSessionId } = useChatSessions();
  const activeProject = useActiveProject();
  const priorSessionIdRef = useRef(currentChatSessionId);
  useEffect(() => {
    const priorSessionId = priorSessionIdRef.current;
    priorSessionIdRef.current = currentChatSessionId;

    const wasOwnSend = keepThroughNextSessionChangeRef.current;
    keepThroughNextSessionChangeRef.current = false;
    // Both parts are required: the flag alone would also excuse an agent or
    // project change that happened to land first.
    if (
      wasOwnSend &&
      priorSessionId === null &&
      currentChatSessionId !== null
    ) {
      return;
    }

    clearForcedTool();
  }, [agent?.id, currentChatSessionId, activeProject?.id, clearForcedTool]);

  // Memoized so consumers re-render when the forced tool changes and not
  // merely because the provider did.
  return useMemo(
    () => ({
      forcedToolId,
      toggleForcedTool,
      clearForcedTool,
      keepThroughNextSessionChange,
    }),
    [
      forcedToolId,
      toggleForcedTool,
      clearForcedTool,
      keepThroughNextSessionChange,
    ]
  );
}

/**
 * Scoped to whatever tree mounts the provider, so one chat surface cannot
 * disturb another's choice. A preview modal over a conversation gets its own,
 * and opening it leaves the conversation's forced tool alone — which a
 * module-level store could not promise without every new surface remembering
 * to be careful.
 *
 * Mount above whatever reads it: the tools popover, the chip in the input bar,
 * and the send path all do, and the send path runs from the page itself.
 */
export const [ForcedToolsProvider, useForcedTools] = createSharedHook(
  useForcedToolsState,
  "ForcedTools"
);

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
