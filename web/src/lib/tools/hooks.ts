"use client";

import useSWR, { mutate } from "swr";
import { useCallback, useEffect, useMemo, useState } from "react";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";
import type {
  AgentEditorMCPServer,
  MCPServersResponse,
  ToolSnapshot,
  ToolState,
} from "@/lib/tools/types";
import { useAppPosition } from "@/lib/position/hooks";
import { useActiveAgent } from "@/lib/agents/hooks";

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

// # NOTE (@raunakab):
// ## The tool configuration
//
// What a message is sent with — the tool it must use, the tools it may not —
// belongs to the chat it was chosen in, and returning any of it to neutral is
// always something the user does. Nothing below is exported: a configuration
// is only reachable through `useToolConfiguration`, so the two rules that hold
// it together cannot be worked around by building one somewhere else.

type ToolConfiguration = Readonly<Record<number, ToolState>>;

const NEUTRAL: ToolConfiguration = {};

const STORAGE_PREFIX = "onyx:tools";

function chatKey(chatSessionId: string): string {
  return `${STORAGE_PREFIX}:chat:${chatSessionId}`;
}

/** Whether this key names a chat that exists, which is the only kind kept. */
function isChatKey(key: string): boolean {
  return key.startsWith(`${STORAGE_PREFIX}:chat:`);
}

/**
 * Applies the one rule a map cannot state: a single tool is forced at a time,
 * because a message carries a single `forced_tool_id`. That a tool is forced,
 * disabled or neutral and never two of those comes free, since a key holds one
 * value.
 *
 * The next state arrives as a function of the current one, so a caller never
 * reads before writing. Reading first is what let the server-side version of
 * this rebuild a list from a value that had not loaded, and delete entries it
 * had never seen.
 */
function withToolState(
  configuration: ToolConfiguration,
  toolId: number,
  change: (current: ToolState | null) => ToolState | null
): ToolConfiguration {
  const next = change(configuration[toolId] ?? null);

  const updated: Record<number, ToolState> = {};
  for (const key of Object.keys(configuration)) {
    const id = Number(key);
    if (id === toolId) continue;
    // Forcing this tool releases whatever was forced before it.
    if (next === "forced" && configuration[id] === "forced") continue;
    updated[id] = configuration[id]!;
  }
  if (next !== null) updated[toolId] = next;

  // A change that changes nothing hands back what it was given. Callers read
  // the result by identity to decide whether anything happened.
  const ids = Object.keys(updated);
  const same =
    ids.length === Object.keys(configuration).length &&
    ids.every((id) => updated[Number(id)] === configuration[Number(id)]);

  return same ? configuration : updated;
}

/**
 * Reads a configuration back from untrusted text.
 *
 * The rules are applied again rather than assumed: storage can be edited by
 * hand, and an older build may have written a shape this one does not know. So
 * text claiming two forced tools keeps one, and anything unrecognised is
 * dropped instead of carried through.
 */
function parseConfiguration(raw: string): ToolConfiguration {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return NEUTRAL;
  }
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return NEUTRAL;
  }
  // SAFETY: narrowed to a non-array object above, and every entry below is
  // checked before it is kept.
  const entries = value as Record<string, unknown>;

  const configuration: Record<number, ToolState> = {};
  let hasForced = false;
  for (const key of Object.keys(entries)) {
    const toolId = Number(key);
    if (!Number.isInteger(toolId)) continue;

    const state = entries[key];
    if (state === "disabled") {
      configuration[toolId] = "disabled";
    } else if (state === "forced" && !hasForced) {
      hasForced = true;
      configuration[toolId] = "forced";
    }
  }
  return configuration;
}

/** Session storage throws outright rather than degrading when it is blocked. */
function storage(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

function readConfiguration(key: string): ToolConfiguration {
  const store = storage();
  if (!store) return NEUTRAL;
  try {
    const raw = store.getItem(key);
    return raw === null ? NEUTRAL : parseConfiguration(raw);
  } catch {
    return NEUTRAL;
  }
}

/**
 * A configuration saying nothing is not stored, so "no entry" and "everything
 * neutral" are one state. That is what lets an entry renamed away leave a fresh
 * composer at its defaults without anything having to clear it.
 */
function clearConfiguration(key: string) {
  const store = storage();
  if (!store) return;
  try {
    store.removeItem(key);
  } catch {
    // Nothing to do; it will be overwritten or ignored.
  }
}

function writeConfiguration(key: string, configuration: ToolConfiguration) {
  const store = storage();
  if (!store) return;
  try {
    if (Object.keys(configuration).length === 0) store.removeItem(key);
    else store.setItem(key, JSON.stringify(configuration));
  } catch {
    // Blocked or full. The configuration still holds for this composer; only
    // surviving a reload is lost.
  }
}

export interface ToolConfigurationHandle {
  /** What this chat has been told about one tool, or null for neutral. */
  stateOf: (toolId: number) => ToolState | null;
  /**
   * The only way to change a configuration. Forcing a tool releases whatever
   * was forced; a tool returned to neutral is forgotten rather than recorded.
   */
  setToolState: (
    toolId: number,
    change: (current: ToolState | null) => ToolState | null
  ) => void;

  /**
   * What a control that means one state does when clicked: asks for that
   * state, or takes it away when the tool already has it.
   *
   * Here rather than at each caller because every control in the popover wants
   * it, and spelling it out per call site is how the popover ended up with two
   * copies of the same three lines.
   */
  toggleToolState: (toolId: number, state: ToolState) => void;

  /**
   * Releases whatever is forced, for the callers that want no forced tool
   * without caring which one is. Still goes through `setToolState`, so the
   * rules hold.
   */
  clearForcedTool: () => void;

  /** The tool every message in this chat is made to use, if any. */
  forcedToolId: number | null;
  /** The tools the model may not use in this chat. */
  disabledToolIds: number[];

  /**
   * Called by the send path once the message it is sending has created the
   * chat. Puts this configuration on that chat, which is where it starts
   * being kept.
   */
  handOffTo: (chatSessionId: string) => void;

  /**
   * Called by a send that navigates somewhere else to do the sending — the
   * agent viewer, which hands off to `/app` rather than sending in place.
   * Leaves the configuration where that page will find it, once.
   */
  handOffToNewChatWith: (agentId: number) => void;
}

/**
 * The tools this chat will send its next message with.
 *
 * Only a chat that exists keeps its configuration. What is chosen for a chat
 * that does not exist yet — a new session, a new agent chat, a new project
 * chat — lives as long as the composer does and no longer: leaving and coming
 * back starts neutral, because there was never anything to come back to.
 *
 * The exception is a send that navigates in order to send. The agent viewer
 * hands off to `/app` rather than sending in place, so its configuration is
 * left where that page will find it, and picked up once. That is a message in
 * flight rather than state being kept.
 *
 * Keyed by where the user is, so switching agent, chat or project reads a
 * different configuration and there is no reset rule to run. A composer the
 * URL does not describe — the agent viewer's, which sits over the listing —
 * says which agent it is for instead. There is no key at all until the agent
 * resolves: reading in that window is what made the server-side version
 * destructive, since an unresolved value reads as "nothing chosen" and then
 * overwrites something real.
 */
export function useToolConfiguration(
  newChatWithAgentId?: number
): ToolConfigurationHandle {
  const appPosition = useAppPosition();
  const activeAgent = useActiveAgent();

  const key = useMemo(() => {
    // A composer for a chat that the URL does not describe says which agent it
    // is for. The agent viewer is one: it sits over the listing, so where the
    // user is says nothing about the chat its input bar would start.
    if (newChatWithAgentId !== undefined) {
      return `${STORAGE_PREFIX}:new:${newChatWithAgentId}`;
    }

    const chatSessionId = appPosition.chat();
    if (chatSessionId !== null) return chatKey(chatSessionId);

    const agentId = appPosition.agent();
    if (agentId !== null) return `${STORAGE_PREFIX}:new:${agentId}`;

    if (activeAgent === undefined) return null;
    const projectId = appPosition.project();
    return projectId === null
      ? `${STORAGE_PREFIX}:new:${activeAgent.id}`
      : `${STORAGE_PREFIX}:new:${activeAgent.id}:${projectId}`;
  }, [newChatWithAgentId, appPosition, activeAgent]);

  // Tagged with the key it was read for, so a write cannot land on the entry
  // the composer has since moved to.
  const [entry, setEntry] = useState<{
    key: string | null;
    configuration: ToolConfiguration;
  }>({ key: null, configuration: NEUTRAL });

  // Storage is only reachable on the client, so the first paint shows neutral
  // and this corrects it. Every later key change comes from the user moving
  // between chats, which is many frames after anything can be sent.
  useEffect(() => {
    if (key === null) {
      setEntry({ key, configuration: NEUTRAL });
      return;
    }
    const stored = readConfiguration(key);
    // A chat that does not exist yet keeps nothing, so anything found under
    // its key was handed over by a send on its way here. Taken once, then
    // removed, so returning later starts neutral.
    if (!isChatKey(key) && Object.keys(stored).length > 0) {
      clearConfiguration(key);
    }
    setEntry({ key, configuration: stored });
  }, [key]);

  const configuration = entry.key === key ? entry.configuration : NEUTRAL;

  // Written from an effect rather than inside the setter, so two changes made
  // in one tick compose instead of the later one landing on what the earlier
  // one replaced. Only a chat that exists is written: everything else is held
  // for as long as the composer lives and then let go.
  useEffect(() => {
    if (entry.key !== null && isChatKey(entry.key)) {
      writeConfiguration(entry.key, entry.configuration);
    }
  }, [entry]);

  const setToolState = useCallback(
    (
      toolId: number,
      change: (current: ToolState | null) => ToolState | null
    ) => {
      if (key === null) return;
      setEntry((previous) => {
        const current = previous.key === key ? previous.configuration : NEUTRAL;
        const configuration = withToolState(current, toolId, change);
        // Asking for the state it already holds has to leave the same entry
        // behind. A new one every time is a change to everything reading it,
        // and a caller that writes what it reads would never settle.
        if (previous.key === key && configuration === current) return previous;
        return { key, configuration };
      });
    },
    [key]
  );

  // Both land before the position that follows reaches this hook, so the key
  // change reads the configuration back where it was left.
  const handOffTo = useCallback(
    (chatSessionId: string) =>
      writeConfiguration(chatKey(chatSessionId), configuration),
    [configuration]
  );

  const handOffToNewChatWith = useCallback(
    (agentId: number) =>
      writeConfiguration(`${STORAGE_PREFIX}:new:${agentId}`, configuration),
    [configuration]
  );

  return useMemo(() => {
    const ids = Object.keys(configuration).map(Number);
    const forcedToolId =
      ids.find((toolId) => configuration[toolId] === "forced") ?? null;
    return {
      stateOf: (toolId: number) => configuration[toolId] ?? null,
      setToolState,
      toggleToolState: (toolId: number, state: ToolState) =>
        setToolState(toolId, (current) => (current === state ? null : state)),
      clearForcedTool: () => {
        if (forcedToolId !== null) setToolState(forcedToolId, () => null);
      },
      forcedToolId,
      disabledToolIds: ids.filter(
        (toolId) => configuration[toolId] === "disabled"
      ),
      handOffTo,
      handOffToNewChatWith,
    };
  }, [configuration, setToolState, handOffTo, handOffToNewChatWith]);
}
