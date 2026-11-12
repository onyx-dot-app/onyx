"use client";

import { useTranslations } from "next-intl";
import useSWR from "swr";
import { useCallback, useEffect, useMemo, useState } from "react";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";
import type {
  ChatSearchFilters,
  ChatToolSelection,
  ToolSnapshot,
  ToolState,
} from "@/lib/tools/types";
export type { ChatSearchFilters } from "@/lib/tools/types";
import type { TagSelection } from "@/lib/searchFilters/types";
import type { MinimalAgent } from "@/lib/agents/types";
import { useAppPosition } from "@/lib/navigation/hooks";
import { useActiveAgent } from "@/lib/agents/hooks";
import { toast } from "@opal/layouts";
import { type MemberPlugin, useMemberPlugins } from "@/lib/plugins/member";
import {
  effectiveChatPreferredToolId,
  enabledChatToolIds,
} from "@/lib/plugins/chat";
import { useUser } from "@/providers/UserProvider";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import {
  CODING_AGENT_TOOL_ID,
  FILE_READER_TOOL_ID,
  IMAGE_GENERATION_TOOL_ID,
  KNOWLEDGE_GRAPH_TOOL_ID,
  MEMORY_TOOL_ID,
  OPEN_URL_TOOL_ID,
  PYTHON_TOOL_ID,
  SEARCH_TOOL_ID,
  WEB_SEARCH_TOOL_ID,
} from "@/lib/tools/constants";

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

// Tool preferences, permissions, and source filters belong to the chat.
// Sending a message preserves the selection.

type ToolConfiguration = Readonly<Record<number, ToolState>>;

/** Everything a chat's next message is configured with. */
interface ChatConfiguration {
  tools: ToolConfiguration;
  filters: ChatSearchFilters;
}

const NEUTRAL_FILTERS: ChatSearchFilters = {
  selectedSources: null,
  documentSets: [],
  tags: [],
  timeRange: null,
};

const NEUTRAL: ChatConfiguration = {
  tools: {},
  filters: NEUTRAL_FILTERS,
};

function isNeutralFilters(filters: ChatSearchFilters): boolean {
  return (
    filters.selectedSources === null &&
    filters.documentSets.length === 0 &&
    filters.tags.length === 0 &&
    filters.timeRange === null
  );
}

function isNeutralConfiguration(configuration: ChatConfiguration): boolean {
  return (
    Object.keys(configuration.tools).length === 0 &&
    isNeutralFilters(configuration.filters)
  );
}

const STORAGE_PREFIX = "onyx:tools";

const EMPTY_SELECTION: ChatToolSelection = {
  allowed_tool_ids: null,
  preferred_tool_id: null,
  internal_search_filters: null,
};
// The halves of a selection that change together: the tool controls own the
// first, the search filters the second. A save sends only the halves the user
// changed, so a change to one never rewrites the other.
const SELECTION_HALVES: readonly (readonly (keyof ChatToolSelection)[])[] = [
  ["allowed_tool_ids", "preferred_tool_id"],
  ["internal_search_filters"],
];

// One save loop per chat, shared by every composer: it sends the chat's
// unsaved edits, then any made while that request ran, so the server ends with
// the latest choice and requests never overlap.
const toolSelectionSaves = new Map<string, Promise<void>>();
// The configuration a send chose for the chat it created, picked up once by
// the composer that moves onto that chat.
const handedOffConfigurations = new Map<string, ChatConfiguration>();

function chatKey(chatSessionId: string): string {
  return `${STORAGE_PREFIX}:chat:${chatSessionId}`;
}

/** Whether this key names a chat that exists, which is the only kind kept. */
function isChatKey(key: string): boolean {
  return key.startsWith(`${STORAGE_PREFIX}:chat:`);
}

/**
 * Applies the one rule a map cannot state: a single tool is preferred at a time,
 * because a message carries a single `preferred_tool_id`. That a tool is preferred,
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
    // Preferring this tool releases whatever was preferred before it.
    if (next === "preferred" && configuration[id] === "preferred") continue;
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

/** Narrows without a cast: predicates carry the proof the checks make. */
function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isUnknownArray(value: unknown): value is readonly unknown[] {
  return Array.isArray(value);
}

function isStringArray(value: unknown): value is string[] {
  return (
    isUnknownArray(value) && value.every((item) => typeof item === "string")
  );
}

/** A stored row is kept only when it names a tag's key and value. */
function isTagSelection(value: unknown): value is TagSelection {
  return (
    isRecord(value) &&
    typeof value.tag_key === "string" &&
    typeof value.tag_value === "string"
  );
}

function isTagSelectionArray(value: unknown): value is TagSelection[] {
  return isUnknownArray(value) && value.every(isTagSelection);
}

/** The filter half of {@link parseConfiguration}, on an already-checked object. */
function parseFilters(entries: Record<string, unknown>): ChatSearchFilters {
  const range = entries.timeRange;
  const timeRange =
    isRecord(range) && typeof range.from === "string"
      ? { from: range.from }
      : null;

  return {
    selectedSources: isStringArray(entries.selectedSources)
      ? entries.selectedSources
      : null,
    documentSets: isStringArray(entries.documentSets)
      ? entries.documentSets
      : [],
    tags: isTagSelectionArray(entries.tags)
      ? entries.tags.map(({ tag_key, tag_value }) => ({ tag_key, tag_value }))
      : [],
    timeRange,
  };
}

/** The tool half of {@link parseConfiguration}, on an already-checked object. */
function parseTools(entries: Record<string, unknown>): ToolConfiguration {
  const configuration: Record<number, ToolState> = {};
  let hasPreferred = false;
  for (const key of Object.keys(entries)) {
    const toolId = Number(key);
    if (!Number.isInteger(toolId)) continue;

    const state = entries[key];
    if (state === "disabled") {
      configuration[toolId] = "disabled";
    } else if (state === "preferred" && !hasPreferred) {
      hasPreferred = true;
      configuration[toolId] = "preferred";
    }
  }
  return configuration;
}

/**
 * Reads a configuration back from untrusted text.
 *
 * The rules are applied again rather than assumed: storage can be edited by
 * hand, and an older build may have written a shape this one does not know. So
 * text claiming two preferred tools keeps one, and anything unrecognised is
 * dropped instead of carried through.
 *
 * A build before the filters moved in wrote the tool map bare. That shape is
 * still read: an object without a `tools` key is taken as the tool map, with
 * the filters at their defaults.
 */
function parseConfiguration(raw: string): ChatConfiguration {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return NEUTRAL;
  }
  if (!isRecord(value)) return NEUTRAL;

  if (isRecord(value.tools)) {
    return {
      tools: parseTools(value.tools),
      filters: isRecord(value.filters)
        ? parseFilters(value.filters)
        : NEUTRAL_FILTERS,
    };
  }
  return {
    tools: parseTools(value),
    filters: NEUTRAL_FILTERS,
  };
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

function readConfiguration(key: string): ChatConfiguration {
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

function writeConfiguration(key: string, configuration: ChatConfiguration) {
  const store = storage();
  if (!store) return;
  try {
    if (isNeutralConfiguration(configuration)) store.removeItem(key);
    else store.setItem(key, JSON.stringify(configuration));
  } catch {
    // Blocked or full. The configuration still holds for this composer; only
    // surviving a reload is lost.
  }
}

/** The selection a chat runs with: the server's copy under unsaved edits. */
function effectiveSelection(
  saved: ChatToolSelection | null | undefined,
  edits: Partial<ChatToolSelection> | undefined
): ChatToolSelection | undefined {
  if (saved === undefined && edits === undefined) return undefined;
  return { ...EMPTY_SELECTION, ...saved, ...edits };
}

/** Reads a saved selection as the composer's tool states and filters. */
function configurationFrom(
  selection: ChatToolSelection,
  agentTools: readonly ToolSnapshot[]
): ChatConfiguration {
  const tools: Record<number, ToolState> = {};
  const allowed = selection.allowed_tool_ids;
  if (allowed !== null) {
    for (const tool of agentTools) {
      if (!allowed.includes(tool.id)) tools[tool.id] = "disabled";
    }
  }
  if (selection.preferred_tool_id !== null) {
    tools[selection.preferred_tool_id] = "preferred";
  }
  const filters = selection.internal_search_filters;
  const rangeStart = filters?.updated_at_range?.start ?? null;
  return {
    tools,
    filters: {
      selectedSources: filters?.source_type ?? null,
      documentSets: filters?.document_set ?? [],
      tags: (filters?.tags ?? []).map(({ tag_key, tag_value }) => ({
        tag_key,
        tag_value,
      })),
      timeRange: rangeStart === null ? null : { from: String(rangeStart) },
    },
  };
}

/** The tool half of a selection, built the way a send builds it. */
function toolFields(
  tools: ToolConfiguration,
  agent: MinimalAgent,
  plugins: readonly MemberPlugin[]
): Pick<ChatToolSelection, "allowed_tool_ids" | "preferred_tool_id"> {
  const ids = Object.keys(tools).map(Number);
  return {
    allowed_tool_ids:
      enabledChatToolIds(agent.tools, {
        disabledToolIds: ids.filter((id) => tools[id] === "disabled"),
      }) ?? null,
    preferred_tool_id: effectiveChatPreferredToolId({
      requestedToolId: ids.find((id) => tools[id] === "preferred") ?? null,
      agent,
      plugins,
    }),
  };
}

/**
 * The filter half of a selection. Sources are stored as the user chose them,
 * not resolved against the connector roster: that resolution belongs to a
 * send, and a roster that has not loaded must not erase a saved choice.
 */
function filterFields(
  filters: ChatSearchFilters
): Pick<ChatToolSelection, "internal_search_filters"> {
  return {
    internal_search_filters: {
      source_type:
        filters.selectedSources === null ? null : [...filters.selectedSources],
      document_set:
        filters.documentSets.length > 0 ? [...filters.documentSets] : null,
      updated_at_range: filters.timeRange
        ? { start: filters.timeRange.from, end: null }
        : null,
      tags: [...filters.tags],
    },
  };
}

/**
 * Applies a save's outcome: `stored` is what the server keeps (null when the
 * chat keeps nothing, which leaves the tab's copy), undefined when the save
 * failed. The halves the request carried leave the unsaved edits unless the
 * user changed them again meanwhile; a failed half falls back to the server's
 * copy.
 */
function settleToolSelectionSave(
  chatSessionId: string,
  sent: Partial<ChatToolSelection>,
  stored: ChatToolSelection | null | undefined
): void {
  const store = useChatSessionStore.getState();
  const session = store.sessions.get(chatSessionId);
  const edits: Partial<ChatToolSelection> = {
    ...session?.toolSelectionEdits,
  };
  for (const half of SELECTION_HALVES) {
    if (
      half.every(
        (field) =>
          field in sent &&
          JSON.stringify(edits[field]) === JSON.stringify(sent[field])
      )
    ) {
      for (const field of half) delete edits[field];
    }
  }
  store.updateSessionData(chatSessionId, {
    toolSelectionEdits: Object.keys(edits).length > 0 ? edits : undefined,
    ...(stored !== undefined && {
      toolSelection: stored ?? {
        ...EMPTY_SELECTION,
        ...session?.toolSelection,
        ...sent,
      },
    }),
  });
}

function saveToolSelectionEdits(
  chatSessionId: string,
  onFailure: () => void
): Promise<void> {
  const running = toolSelectionSaves.get(chatSessionId);
  if (running !== undefined) return running;
  const run = (async () => {
    // Lets the entry below register before the first read.
    await Promise.resolve();
    try {
      for (;;) {
        const sent = useChatSessionStore
          .getState()
          .sessions.get(chatSessionId)?.toolSelectionEdits;
        if (sent === undefined) return;
        let stored: ChatToolSelection | null;
        try {
          const response = await fetch(
            `/api/chat/chat-session/${chatSessionId}/tool-selection`,
            {
              method: "PATCH",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(sent),
              // A reload right after a change still delivers it.
              keepalive: true,
            }
          );
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          stored = await response.json();
        } catch (error: unknown) {
          console.error("Could not save the chat's tool selection", error);
          onFailure();
          settleToolSelectionSave(chatSessionId, sent, undefined);
          return;
        }
        settleToolSelectionSave(chatSessionId, sent, stored);
      }
    } finally {
      toolSelectionSaves.delete(chatSessionId);
    }
  })();
  toolSelectionSaves.set(chatSessionId, run);
  return run;
}

/**
 * Resolves once the chat's tool-selection save has finished, so a turn the
 * server starts next reads the user's latest choice.
 */
export function flushToolSelection(chatSessionId: string): Promise<void> {
  return toolSelectionSaves.get(chatSessionId) ?? Promise.resolve();
}

export interface ToolConfigurationHandle {
  /** What this chat has been told about one tool, or null for neutral. */
  stateOf: (toolId: number) => ToolState | null;
  /**
   * The only way to change a tool's state. Preferring a tool releases whatever
   * was preferred; a tool returned to neutral is forgotten rather than recorded.
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
   * Releases whatever is preferred, for the callers that want no preferred tool
   * without caring which one is. Still goes through `setToolState`, so the
   * rules hold.
   */
  clearPreferredTool: () => void;
  /** The preferred tool for this chat, if any. */
  preferredToolId: number | null;
  /** The tools the model may not use in this chat. */
  disabledToolIds: number[];

  /**
   * Whether writes land yet: the composer's key has resolved and its
   * configuration has been read — from the server for an existing chat, from
   * session storage otherwise. Until then `setToolState` and `setFilters`
   * are silently dropped, so a caller sequencing work on a fresh mount — the
   * deep-link send — must wait for this.
   */
  ready: boolean;

  /**
   * The search filters this chat sends with. Orthogonal to the tool states:
   * changing one never changes the other.
   */
  filters: ChatSearchFilters;
  /**
   * The only way to change the filters. The next value arrives as a function
   * of the current one for the same reason `setToolState`'s does; a change
   * that returns its input leaves the entry untouched.
   */
  setFilters: (
    change: (current: ChatSearchFilters) => ChatSearchFilters
  ) => void;

  /**
   * Called by the send path once the message it is sending has created the
   * chat. Carries this configuration onto that chat, whose composer saves it
   * on the server.
   */
  handOffTo: (chatSessionId: string) => void;

  /**
   * Called by a send that navigates somewhere else to do the sending — the
   * agent viewer, which hands off to `/app` rather than sending in place.
   * Leaves the configuration where that page will find it, once.
   */
  handOffToNewChatWith: (agentId: number, projectId?: number | null) => void;
}

/**
 * The tools and search filters this chat will send its next message with.
 *
 * Only a chat that exists keeps its configuration, and the server owns it: the
 * chat-session detail returns it, and the tool-selection PATCH is its only
 * writer. A send never changes it, so a one-message choice such as Deep
 * Research cannot leak into the chat. The server keeps nothing for a chat that
 * stores no content, so this tab holds that chat's only copy. What is chosen
 * for a chat that does not exist yet — a new session, a new agent chat, a new
 * project chat — lives as long as the composer does and no longer: leaving
 * and coming back starts neutral, because there was never anything to come
 * back to.
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

  const { user } = useUser();
  const { plugins } = useMemberPlugins({
    agentId: activeAgent?.id,
    surface: "chat",
  });
  const chatSessionId =
    newChatWithAgentId === undefined ? appPosition.chat() : null;
  // The server's copy of an existing chat's selection, undefined until its
  // details load, and the user's edits that the server has not confirmed.
  // The store holds both for every composer, so a remount or a chat switch
  // never loses a choice whose save is still running.
  const savedSelection = useChatSessionStore((state) =>
    chatSessionId === null
      ? undefined
      : state.sessions.get(chatSessionId)?.toolSelection
  );
  const selectionEdits = useChatSessionStore((state) =>
    chatSessionId === null
      ? undefined
      : state.sessions.get(chatSessionId)?.toolSelectionEdits
  );
  const agentTools = activeAgent?.tools;

  // A chat that does not exist yet keeps its configuration here, tagged with
  // the key it was read for, so a write cannot land on the entry the composer
  // has since moved to.
  const [entry, setEntry] = useState<{
    key: string | null;
    configuration: ChatConfiguration;
  }>({ key: null, configuration: NEUTRAL });

  // Storage is only reachable on the client, so the first paint shows neutral
  // and this corrects it.
  useEffect(() => {
    if (key !== null && isChatKey(key)) return;
    // Kept only until it is read: a chat that does not exist yet keeps
    // nothing.
    setEntry({
      key,
      configuration: key === null ? NEUTRAL : readConfiguration(key),
    });
    if (key !== null) clearConfiguration(key);
  }, [key]);

  // A configuration handed to the chat a send just created becomes that
  // chat's edits, which its composer then saves.
  useEffect(() => {
    if (key === null || chatSessionId === null || activeAgent === undefined) {
      return;
    }
    const handedOff = handedOffConfigurations.get(key);
    if (handedOff === undefined) return;
    handedOffConfigurations.delete(key);
    useChatSessionStore.getState().updateSessionData(chatSessionId, {
      toolSelectionEdits: {
        ...toolFields(handedOff.tools, activeAgent, plugins),
        ...filterFields(handedOff.filters),
      },
    });
  }, [key, chatSessionId, activeAgent, plugins]);

  const chatConfiguration = useMemo(() => {
    const selection = effectiveSelection(savedSelection, selectionEdits);
    return selection === undefined || agentTools === undefined
      ? null
      : configurationFrom(selection, agentTools);
  }, [savedSelection, selectionEdits, agentTools]);

  const isChat = key !== null && isChatKey(key);
  const configuration = isChat
    ? (chatConfiguration ?? NEUTRAL)
    : entry.key === key
      ? entry.configuration
      : NEUTRAL;
  const ready = isChat
    ? chatConfiguration !== null
    : key !== null && entry.key === key;

  // An edit in an existing chat updates the store's edits from the store's
  // current state, so edits made back to back each see the one before.
  // Until the chat's details load the edit is dropped: built on nothing, it
  // would overwrite the saved choice.
  const editChat = useCallback(
    (
      change: (current: ChatConfiguration) => Partial<ChatToolSelection> | null
    ) => {
      if (chatSessionId === null || activeAgent === undefined) return;
      const store = useChatSessionStore.getState();
      const session = store.sessions.get(chatSessionId);
      const selection = effectiveSelection(
        session?.toolSelection,
        session?.toolSelectionEdits
      );
      if (selection === undefined) return;
      const fields = change(configurationFrom(selection, activeAgent.tools));
      if (fields === null) return;
      store.updateSessionData(chatSessionId, {
        toolSelectionEdits: { ...session?.toolSelectionEdits, ...fields },
      });
    },
    [chatSessionId, activeAgent]
  );

  const setToolState = useCallback(
    (
      toolId: number,
      change: (current: ToolState | null) => ToolState | null
    ) => {
      if (key === null) return;
      if (isChatKey(key)) {
        editChat((current) => {
          const tools = withToolState(current.tools, toolId, change);
          return tools === current.tools || activeAgent === undefined
            ? null
            : toolFields(tools, activeAgent, plugins);
        });
        return;
      }
      setEntry((previous) => {
        // Between a key change and its read, a write would land on NEUTRAL
        // and then be clobbered by the read. `ready` documents that writes
        // are dropped in that window; this is the drop.
        if (previous.key !== key) return previous;
        const current = previous.configuration;
        const tools = withToolState(current.tools, toolId, change);
        // Asking for the state it already holds has to leave the same entry
        // behind. A new one every time is a change to everything reading it,
        // and a caller that writes what it reads would never settle.
        if (tools === current.tools) return previous;
        return { key, configuration: { ...current, tools } };
      });
    },
    [key, editChat, activeAgent, plugins]
  );

  const setFilters = useCallback(
    (change: (current: ChatSearchFilters) => ChatSearchFilters) => {
      if (key === null) return;
      if (isChatKey(key)) {
        editChat((current) => {
          const filters = change(current.filters);
          return filters === current.filters ? null : filterFields(filters);
        });
        return;
      }
      setEntry((previous) => {
        if (previous.key !== key) return previous;
        const current = previous.configuration;
        const filters = change(current.filters);
        if (filters === current.filters) return previous;
        return { key, configuration: { ...current, filters } };
      });
    },
    [key, editChat]
  );

  // Lands before the position that follows reaches this hook, so the key
  // change picks the configuration up.
  const handOffTo = useCallback(
    (newChatSessionId: string) =>
      handedOffConfigurations.set(chatKey(newChatSessionId), configuration),
    [configuration]
  );

  const handOffToNewChatWith = useCallback(
    (agentId: number, projectId: number | null = null) =>
      writeConfiguration(
        projectId === null
          ? `${STORAGE_PREFIX}:new:${agentId}`
          : `${STORAGE_PREFIX}:new:${agentId}:${projectId}`,
        configuration
      ),
    [configuration]
  );

  const handle = useMemo(() => {
    const ids = Object.keys(configuration.tools).map(Number);
    const preferredToolId =
      ids.find((toolId) => configuration.tools[toolId] === "preferred") ?? null;
    return {
      stateOf: (toolId: number) => configuration.tools[toolId] ?? null,
      setToolState,
      toggleToolState: (toolId: number, state: ToolState) =>
        setToolState(toolId, (current) => (current === state ? null : state)),
      clearPreferredTool: () => {
        if (preferredToolId !== null) {
          setToolState(preferredToolId, (current) =>
            current === "preferred" ? null : current
          );
        }
      },
      preferredToolId,
      disabledToolIds: ids.filter(
        (toolId) => configuration.tools[toolId] === "disabled"
      ),
      ready,
      filters: configuration.filters,
      setFilters,
      handOffTo,
      handOffToNewChatWith,
    };
  }, [
    configuration,
    ready,
    setToolState,
    setFilters,
    handOffTo,
    handOffToNewChatWith,
  ]);

  // Edits in an existing chat are saved on the server at once, which decides
  // whether the chat keeps them. Only a signed-in user saves.
  const t = useTranslations("actions");
  const signedIn = user !== null && !user.is_anonymous_user;
  useEffect(() => {
    if (chatSessionId === null || !signedIn || selectionEdits === undefined) {
      return;
    }
    void saveToolSelectionEdits(chatSessionId, () =>
      toast.error(t("toolsPopover.selectionSaveFailed"))
    );
  }, [chatSessionId, signedIn, selectionEdits, t]);

  return handle;
}

/**
 * Display names for the built-in tools, keyed by `in_code_tool_id`.
 *
 * The backend names these in English, which is right for the model but not for
 * the UI, so a row reads its name from here instead. Spelled out rather than
 * looked up dynamically because next-intl types its keys, and a lookup by
 * variable would give up that checking.
 *
 * Only in-code tools appear. A tool defined through the UI or served by an MCP
 * server is named by whoever created it, and there is nothing to translate.
 */
export function useBuiltInToolNames(): Record<string, string> {
  const t = useTranslations("actions");
  return useMemo(
    () => ({
      [SEARCH_TOOL_ID]: t("toolNames.internalSearch.label"),
      [IMAGE_GENERATION_TOOL_ID]: t("toolNames.imageGeneration.label"),
      [WEB_SEARCH_TOOL_ID]: t("toolNames.webSearch.label"),
      [KNOWLEDGE_GRAPH_TOOL_ID]: t("toolNames.knowledgeGraph.label"),
      [OPEN_URL_TOOL_ID]: t("toolNames.openUrl.label"),
      [PYTHON_TOOL_ID]: t("toolNames.codeInterpreter.label"),
      [FILE_READER_TOOL_ID]: t("toolNames.fileReader.label"),
      [MEMORY_TOOL_ID]: t("toolNames.addMemory.label"),
      [CODING_AGENT_TOOL_ID]: t("toolNames.codingAgent.label"),
    }),
    [t]
  );
}
