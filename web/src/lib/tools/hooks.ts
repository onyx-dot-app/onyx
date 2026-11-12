"use client";

import { useTranslations } from "next-intl";
import useSWR from "swr";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import { useAppPosition } from "@/lib/navigation/hooks";
import { useActiveAgent } from "@/lib/agents/hooks";
import { toast } from "@opal/layouts";
import { useMemberPlugins } from "@/lib/plugins/member";
import {
  effectiveChatPreferredToolId,
  enabledChatToolIds,
} from "@/lib/plugins/chat";
import { useUser } from "@/providers/UserProvider";
import { useChatSearchFiltersRequest } from "@/lib/searchFilters/hooks";
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
const TOOL_SELECTION_SYNC_MS = 300;

// Saves for one chat run one at a time across every composer, so the server
// keeps the latest selection even when a composer remounts mid-save.
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
  // The server's selection for an existing chat; undefined until its details
  // load.
  const savedSelection = useChatSessionStore((state) =>
    chatSessionId === null
      ? undefined
      : state.sessions.get(chatSessionId)?.toolSelection
  );
  const agentTools = activeAgent?.tools;

  // Tagged with the key it was read for, so a write cannot land on the entry
  // the composer has since moved to. `local` marks choices this composer made
  // or carried over, which the server's copy no longer replaces; `saved` is
  // the server's copy an entry was read from.
  const [entry, setEntry] = useState<{
    key: string | null;
    configuration: ChatConfiguration;
    local: boolean;
    saved?: ChatToolSelection | null;
  }>({ key: null, configuration: NEUTRAL, local: false });

  // Storage and the chat's details are only reachable on the client, so the
  // first paint shows neutral and this corrects it. Every later key change
  // comes from the user moving between chats, which is many frames after
  // anything can be sent.
  useEffect(() => {
    if (key === null) {
      setEntry({ key, configuration: NEUTRAL, local: false });
      return;
    }
    if (!isChatKey(key)) {
      // Kept only until it is read: a chat that does not exist yet keeps
      // nothing.
      setEntry({ key, configuration: readConfiguration(key), local: false });
      clearConfiguration(key);
      return;
    }
    const handedOff = handedOffConfigurations.get(key);
    if (handedOff !== undefined) {
      handedOffConfigurations.delete(key);
      setEntry({ key, configuration: handedOff, local: true });
      return;
    }
    if (savedSelection === undefined || agentTools === undefined) return;
    setEntry((previous) => {
      if (
        previous.key === key &&
        (previous.local || previous.saved === savedSelection)
      ) {
        return previous;
      }
      const tools: Record<number, ToolState> = {};
      const allowed = savedSelection?.allowed_tool_ids ?? null;
      if (allowed !== null) {
        for (const tool of agentTools) {
          if (!allowed.includes(tool.id)) tools[tool.id] = "disabled";
        }
      }
      const preferred = savedSelection?.preferred_tool_id ?? null;
      if (preferred !== null) tools[preferred] = "preferred";
      const filters = savedSelection?.internal_search_filters ?? null;
      const rangeStart = filters?.updated_at_range?.start ?? null;
      return {
        key,
        configuration: {
          tools,
          filters: {
            selectedSources: filters?.source_type ?? null,
            documentSets: filters?.document_set ?? [],
            tags: (filters?.tags ?? []).map(({ tag_key, tag_value }) => ({
              tag_key,
              tag_value,
            })),
            timeRange:
              rangeStart === null ? null : { from: String(rangeStart) },
          },
        },
        local: false,
        saved: savedSelection,
      };
    });
  }, [key, savedSelection, agentTools]);

  const configuration = entry.key === key ? entry.configuration : NEUTRAL;
  const ready = key !== null && entry.key === key;

  const setToolState = useCallback(
    (
      toolId: number,
      change: (current: ToolState | null) => ToolState | null
    ) => {
      if (key === null) return;
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
        return { key, configuration: { ...current, tools }, local: true };
      });
    },
    [key]
  );

  const setFilters = useCallback(
    (change: (current: ChatSearchFilters) => ChatSearchFilters) => {
      if (key === null) return;
      setEntry((previous) => {
        if (previous.key !== key) return previous;
        const current = previous.configuration;
        const filters = change(current.filters);
        if (filters === current.filters) return previous;
        return { key, configuration: { ...current, filters }, local: true };
      });
    },
    [key]
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

  // A choice made in an existing chat is saved on the server, which decides
  // whether the chat keeps it. Only a signed-in user saves.
  const t = useTranslations("actions");
  const searchFilters = useChatSearchFiltersRequest(
    activeAgent,
    configuration.filters
  );
  const selection: ChatToolSelection | null =
    ready &&
    entry.local &&
    chatSessionId !== null &&
    activeAgent !== undefined &&
    user !== null &&
    !user.is_anonymous_user
      ? {
          // The fields a send carries, built the same way.
          allowed_tool_ids:
            enabledChatToolIds(activeAgent.tools, handle) ?? null,
          preferred_tool_id: effectiveChatPreferredToolId({
            requestedToolId: handle.preferredToolId,
            agent: activeAgent,
            plugins,
          }),
          internal_search_filters: searchFilters,
        }
      : null;
  const body = selection === null ? null : JSON.stringify(selection);
  const pendingSave = useRef<{
    chatSessionId: string;
    timer: ReturnType<typeof setTimeout>;
    send: () => void;
  } | null>(null);
  useEffect(() => {
    if (body === null || chatSessionId === null) return;
    const pending = pendingSave.current;
    if (pending) {
      clearTimeout(pending.timer);
      // A change for another chat is not superseded by this one.
      if (pending.chatSessionId !== chatSessionId) pending.send();
    }
    const send = () => {
      if (pendingSave.current?.chatSessionId === chatSessionId) {
        pendingSave.current = null;
      }
      const save = (
        toolSelectionSaves.get(chatSessionId) ?? Promise.resolve()
      ).then(async () => {
        try {
          const response = await fetch(
            `/api/chat/chat-session/${chatSessionId}/tool-selection`,
            {
              method: "PATCH",
              headers: { "Content-Type": "application/json" },
              body,
            }
          );
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          const stored: ChatToolSelection | null = await response.json();
          const sent: ChatToolSelection = JSON.parse(body);
          // A chat that stores no content keeps its selection only here.
          useChatSessionStore.getState().updateSessionData(chatSessionId, {
            toolSelection: stored ?? sent,
          });
        } catch (error: unknown) {
          console.error("Could not save the chat's tool selection", error);
          toast.error(t("toolsPopover.selectionSaveFailed"));
        }
      });
      toolSelectionSaves.set(chatSessionId, save);
      void save.then(() => {
        if (toolSelectionSaves.get(chatSessionId) === save) {
          toolSelectionSaves.delete(chatSessionId);
        }
      });
    };
    pendingSave.current = {
      chatSessionId,
      timer: setTimeout(send, TOOL_SELECTION_SYNC_MS),
      send,
    };
  }, [chatSessionId, body, t]);
  // A composer that closes before its save is due sends it at once.
  useEffect(
    () => () => {
      const pending = pendingSave.current;
      if (pending === null) return;
      clearTimeout(pending.timer);
      pending.send();
    },
    []
  );

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
