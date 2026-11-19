"use client";

import { useTranslations } from "next-intl";
import useSWR from "swr";
import { useCallback, useEffect, useMemo, useState } from "react";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";
import type {
  ChatSearchFilters,
  ChatToolOptions,
  ActionPreference,
  ToolOptionsEntry,
  ToolSnapshot,
  ToolState,
} from "@/lib/tools/types";
export type { ChatSearchFilters } from "@/lib/tools/types";
import type { TagSelection } from "@/lib/searchFilters/types";
import type { MinimalAgent } from "@/lib/agents/types";
import { useAppPosition } from "@/lib/navigation/hooks";
import { useActiveAgent } from "@/lib/agents/hooks";
import { toast } from "@opal/layouts";
import {
  useAgentIntegrationIds,
  useAgentIntegrationPreferences,
} from "@/lib/integrations/hooks";
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
/** The integrations switched off, by integration id. One not listed is on. */
type IntegrationConfiguration = Readonly<Record<number, "disabled">>;
/**
 * The action keys that saved options keep for an integration, by integration
 * id. One not listed keeps each action. No control edits them; they come from
 * options another client saved and go back unchanged.
 */
type IntegrationActions = Readonly<Record<number, readonly string[]>>;

/** Everything a chat's next message is configured with. */
interface ChatConfiguration {
  tools: ToolConfiguration;
  integrations: IntegrationConfiguration;
  integrationActions: IntegrationActions;
  /** Applies only while no built-in tool is preferred. */
  preferredAction: ActionPreference | null;
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
  integrations: {},
  integrationActions: {},
  preferredAction: null,
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
    Object.keys(configuration.integrations).length === 0 &&
    Object.keys(configuration.integrationActions).length === 0 &&
    configuration.preferredAction === null &&
    isNeutralFilters(configuration.filters)
  );
}

const STORAGE_PREFIX = "onyx:tools";

const EMPTY_OPTIONS: ChatToolOptions = {
  allowed: null,
  preferred: null,
  internal_search_filters: null,
};
// The halves of the options that change together: the tool and integration
// controls own the first, the search filters the second. A save sends only the
// halves the user changed, so a change to one never rewrites the other.
const OPTION_HALVES: readonly (readonly (keyof ChatToolOptions)[])[] = [
  ["allowed", "preferred"],
  ["internal_search_filters"],
];

// One save loop per chat, shared by every composer: it sends the chat's
// unsaved edits, then any made while that request ran, so the server ends with
// the latest choice and requests never overlap.
const toolOptionsSaves = new Map<string, Promise<void>>();
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
 * because a message carries a single preferred tool. That a tool is preferred,
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

/** The integration half of {@link parseConfiguration}, on an already-checked
 * object. A key that is not an integration id goes. */
function parseIntegrations(
  entries: Record<string, unknown>
): IntegrationConfiguration {
  const integrations: Record<number, "disabled"> = {};
  for (const key of Object.keys(entries)) {
    if (/^\d+$/.test(key) && entries[key] === "disabled")
      integrations[Number(key)] = "disabled";
  }
  return integrations;
}

/** The preferred action of {@link parseConfiguration}, on an already-checked object. */
function parsePreferredAction(
  entries: Record<string, unknown>
): ActionPreference | null {
  const value = entries.preferredAction;
  return isRecord(value) &&
    value.type === "action" &&
    typeof value.integration_id === "number" &&
    typeof value.action === "string"
    ? {
        type: "action",
        integration_id: value.integration_id,
        action: value.action,
      }
    : null;
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
      integrations: isRecord(value.integrations)
        ? parseIntegrations(value.integrations)
        : {},
      integrationActions: {},
      preferredAction: parsePreferredAction(value),
      filters: isRecord(value.filters)
        ? parseFilters(value.filters)
        : NEUTRAL_FILTERS,
    };
  }
  return {
    tools: parseTools(value),
    integrations: {},
    integrationActions: {},
    preferredAction: null,
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

/** The options a chat runs with: the server's copy under unsaved edits. */
function effectiveOptions(
  saved: ChatToolOptions | null | undefined,
  edits: Partial<ChatToolOptions> | undefined
): ChatToolOptions | undefined {
  if (saved === undefined && edits === undefined) return undefined;
  return { ...EMPTY_OPTIONS, ...saved, ...edits };
}

/**
 * Reads saved options as the composer's tool and integration states and
 * filters. `integrationIds` is every integration the composer knows: one that
 * `allowed` leaves out is off.
 */
function configurationFrom(
  options: ChatToolOptions,
  agentTools: readonly ToolSnapshot[],
  integrationIds: readonly number[],
  preferredIntegrations: IntegrationConfiguration
): ChatConfiguration {
  const tools: Record<number, ToolState> = {};
  const integrations: Record<number, "disabled"> =
    options.allowed === null ? { ...preferredIntegrations } : {};
  const integrationActions: Record<number, string[] | null> = {};
  const allowed = options.allowed;
  if (allowed !== null) {
    for (const entry of allowed) {
      if (entry.type !== "integration") continue;
      const kept = integrationActions[entry.integration_id];
      integrationActions[entry.integration_id] =
        entry.actions == null || kept === null
          ? null
          : [...new Set([...(kept ?? []), ...entry.actions])];
    }
    for (const tool of agentTools) {
      if (
        tool.in_code_tool_id &&
        !allowed.some(
          (entry) => entry.type === "capability" && entry.tool_id === tool.id
        )
      ) {
        tools[tool.id] = "disabled";
      }
    }
    for (const integrationId of integrationIds) {
      if (
        !allowed.some(
          (entry) =>
            entry.type === "integration" &&
            entry.integration_id === integrationId
        )
      ) {
        integrations[integrationId] = "disabled";
      }
    }
  }
  if (options.preferred?.type === "capability") {
    tools[options.preferred.tool_id] = "preferred";
  }
  const filters = options.internal_search_filters;
  const rangeStart = filters?.updated_at_range?.start ?? null;
  const limited: Record<number, readonly string[]> = {};
  for (const [integrationId, actions] of Object.entries(integrationActions)) {
    if (actions !== null) limited[Number(integrationId)] = actions;
  }
  return {
    tools,
    integrations,
    integrationActions: limited,
    preferredAction:
      options.preferred?.type === "action" ? options.preferred : null,
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

/**
 * The allowed tools and integrations, or null when nothing is off. Only sent then:
 * to the server a list is a whitelist, and this one holds only the built-in
 * tools and the integrations that the frontend knows.
 */
function allowedEntries(
  tools: ToolConfiguration,
  integrations: IntegrationConfiguration,
  integrationActions: IntegrationActions,
  agent: MinimalAgent,
  integrationIds: readonly number[]
): ToolOptionsEntry[] | null {
  if (
    !Object.values(tools).includes("disabled") &&
    Object.keys(integrations).length === 0 &&
    Object.keys(integrationActions).length === 0
  ) {
    return null;
  }
  return [
    ...agent.tools
      .filter((tool) => tool.in_code_tool_id && tools[tool.id] !== "disabled")
      .map(
        (tool): ToolOptionsEntry => ({
          type: "capability",
          tool_id: tool.id,
        })
      ),
    ...integrationIds
      .filter((integrationId) => integrations[integrationId] !== "disabled")
      .map((integrationId): ToolOptionsEntry => {
        const actions = integrationActions[integrationId];
        return actions === undefined
          ? { type: "integration", integration_id: integrationId }
          : {
              type: "integration",
              integration_id: integrationId,
              actions: [...actions],
            };
      }),
  ];
}

function preferredToolIdOf(tools: ToolConfiguration): number | null {
  return (
    Object.keys(tools)
      .map(Number)
      .find((id) => tools[id] === "preferred") ?? null
  );
}

/**
 * Preferring a built-in tool releases a preferred action, because a message
 * carries one preference.
 */
function withTools(
  configuration: ChatConfiguration,
  tools: ToolConfiguration
): ChatConfiguration {
  return {
    ...configuration,
    tools,
    preferredAction:
      preferredToolIdOf(tools) === null ? configuration.preferredAction : null,
  };
}

/**
 * The tool half of the options, as the user chose it. A preferred tool or
 * action that is unavailable right now is kept: a send drops it, and a turn
 * the server starts drops it too.
 */
function toolFields(
  configuration: Pick<
    ChatConfiguration,
    "tools" | "integrations" | "integrationActions" | "preferredAction"
  >,
  agent: MinimalAgent,
  integrationIds: readonly number[]
): Pick<ChatToolOptions, "allowed" | "preferred"> {
  const { tools, integrations, integrationActions, preferredAction } =
    configuration;
  const preferred = preferredToolIdOf(tools);
  return {
    allowed: allowedEntries(
      tools,
      integrations,
      integrationActions,
      agent,
      integrationIds
    ),
    preferred:
      preferred === null
        ? preferredAction
        : { type: "capability", tool_id: preferred },
  };
}

/**
 * The filter half of a selection. Sources are stored as the user chose them,
 * not resolved against the connector roster: that resolution belongs to a
 * send, and a roster that has not loaded must not erase a saved choice.
 */
function filterFields(
  filters: ChatSearchFilters
): Pick<ChatToolOptions, "internal_search_filters"> {
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
function settleToolOptionsSave(
  chatSessionId: string,
  sent: Partial<ChatToolOptions>,
  stored: ChatToolOptions | null | undefined
): void {
  const store = useChatSessionStore.getState();
  const session = store.sessions.get(chatSessionId);
  const edits: Partial<ChatToolOptions> = {
    ...session?.toolOptionsEdits,
  };
  for (const half of OPTION_HALVES) {
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
    toolOptionsEdits: Object.keys(edits).length > 0 ? edits : undefined,
    ...(stored !== undefined && {
      toolOptions: stored ?? {
        ...EMPTY_OPTIONS,
        ...session?.toolOptions,
        ...sent,
      },
      toolOptionsVersion: (session?.toolOptionsVersion ?? 0) + 1,
    }),
  });
}

function saveToolOptionsEdits(
  chatSessionId: string,
  onFailure: () => void
): Promise<void> {
  const running = toolOptionsSaves.get(chatSessionId);
  if (running !== undefined) return running;
  const run = (async () => {
    // Lets the entry below register before the first read.
    await Promise.resolve();
    try {
      for (;;) {
        const sent = useChatSessionStore
          .getState()
          .sessions.get(chatSessionId)?.toolOptionsEdits;
        if (sent === undefined) return;
        let stored: ChatToolOptions | null;
        try {
          const response = await fetch(
            `/api/chat/chat-session/${chatSessionId}/tool-options`,
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
          console.error("Could not save the chat's tool options", error);
          onFailure();
          settleToolOptionsSave(chatSessionId, sent, undefined);
          return;
        }
        settleToolOptionsSave(chatSessionId, sent, stored);
      }
    } finally {
      toolOptionsSaves.delete(chatSessionId);
    }
  })();
  toolOptionsSaves.set(chatSessionId, run);
  return run;
}

/**
 * Resolves once the chat's tool-options save has finished, so a turn the
 * server starts next reads the user's latest choice.
 */
export function flushToolOptions(chatSessionId: string): Promise<void> {
  return toolOptionsSaves.get(chatSessionId) ?? Promise.resolve();
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
  /** The preferred integration action, saved by another client; the tool wins. */
  preferredAction: ActionPreference | null;
  /** The built-in tools the model may not use in this chat. */
  disabledToolIds: number[];
  /** Whether an integration is on for this chat. */
  isIntegrationEnabled: (integrationId: number) => boolean;
  /** Switches integrations on or off for this chat. */
  setIntegrationEnabled: (
    integrationIds: readonly number[],
    enabled: boolean
  ) => void;
  /**
   * The tools and integrations a send allows, or null for every tool and
   * integration of the agent.
   */
  allowed: ToolOptionsEntry[] | null;

  /**
   * Whether writes land yet: the composer's key has resolved and its
   * configuration has been read — from the server for an existing chat, from
   * session storage otherwise. Until then `setToolState` and `setFilters`
   * are silently dropped, so a caller sequencing work on a fresh mount — the
   * deep-link send — must wait for this.
   */
  ready: boolean;

  /**
   * False while an existing chat's saved options, or the integrations a new
   * chat starts with turned off, have not loaded. A send then would carry
   * no allow-list and turn on what the user turned off.
   */
  optionsLoaded: boolean;

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
 * chat-session detail returns it, and the tool-options PATCH is its only
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
  const t = useTranslations("actions");

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
  const signedIn = user !== null && !user.is_anonymous_user;
  // The integrations the user turned off for this agent. A chat that does not
  // exist yet starts with them; a switch in any chat saves them.
  const preferences = useAgentIntegrationPreferences(signedIn);
  // The agent whose integrations this composer reads and saves: the agent viewer
  // names its own.
  const configAgentId = newChatWithAgentId ?? activeAgent?.id;
  const preferredOff =
    configAgentId === undefined
      ? null
      : preferences.disabledIntegrationIds(configAgentId);
  const preferredOffKey = preferredOff === null ? null : preferredOff.join(",");
  const preferredIntegrations = useMemo((): IntegrationConfiguration | null => {
    if (preferredOffKey === null) return null;
    const integrations: Record<number, "disabled"> = {};
    for (const id of preferredOffKey.split(",")) {
      if (id !== "") integrations[Number(id)] = "disabled";
    }
    return integrations;
  }, [preferredOffKey]);
  const chatSessionId =
    newChatWithAgentId === undefined ? appPosition.chat() : null;
  // The server's copy of an existing chat's options, undefined until its
  // details load, and the user's edits that the server has not confirmed.
  // The store holds both for every composer, so a remount or a chat switch
  // never loses a choice whose save is still running.
  const savedOptions = useChatSessionStore((state) =>
    chatSessionId === null
      ? undefined
      : state.sessions.get(chatSessionId)?.toolOptions
  );
  const optionsEdits = useChatSessionStore((state) =>
    chatSessionId === null
      ? undefined
      : state.sessions.get(chatSessionId)?.toolOptionsEdits
  );
  const agentTools = activeAgent?.tools;
  // Every integration of the agent, null until it loads. Saved options name
  // integrations in an allow-list, so one unknown here would be left out.
  const agentIntegrationIds =
    useAgentIntegrationIds(configAgentId).integrationIds;
  const integrationIdsKey =
    agentIntegrationIds === null ? null : agentIntegrationIds.join(",");
  const integrationIds = useMemo(
    () =>
      integrationIdsKey === null
        ? null
        : integrationIdsKey
            .split(",")
            .filter((id) => id !== "")
            .map(Number),
    [integrationIdsKey]
  );

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
    if (
      key === null ||
      chatSessionId === null ||
      activeAgent === undefined ||
      integrationIds === null
    ) {
      return;
    }
    const handedOff = handedOffConfigurations.get(key);
    if (handedOff === undefined) return;
    handedOffConfigurations.delete(key);
    useChatSessionStore.getState().updateSessionData(chatSessionId, {
      toolOptionsEdits: {
        ...toolFields(handedOff, activeAgent, integrationIds),
        ...filterFields(handedOff.filters),
      },
    });
  }, [key, chatSessionId, activeAgent, integrationIds]);

  const chatOptions = useMemo(
    () => effectiveOptions(savedOptions, optionsEdits),
    [savedOptions, optionsEdits]
  );
  // Until the integration catalogs load, the tools and filters come from the saved
  // options and a send carries the saved allow-list as it is.
  const chatConfiguration = useMemo(
    () =>
      chatOptions === undefined || agentTools === undefined
        ? null
        : configurationFrom(
            chatOptions,
            agentTools,
            integrationIds ?? [],
            preferredIntegrations ?? {}
          ),
    [chatOptions, agentTools, integrationIds, preferredIntegrations]
  );

  const isChat = key !== null && isChatKey(key);
  const newChatConfiguration = useMemo(
    () =>
      entry.key !== key
        ? NEUTRAL
        : signedIn
          ? {
              ...entry.configuration,
              integrations: preferredIntegrations ?? {},
            }
          : entry.configuration,
    [entry, key, signedIn, preferredIntegrations]
  );
  const configuration = isChat
    ? (chatConfiguration ?? NEUTRAL)
    : newChatConfiguration;
  const ready = isChat
    ? chatConfiguration !== null &&
      integrationIds !== null &&
      (chatOptions?.allowed !== null || preferredIntegrations !== null)
    : key !== null &&
      entry.key === key &&
      integrationIds !== null &&
      preferredIntegrations !== null;
  const savedAllowed =
    isChat && integrationIds === null && chatOptions !== undefined
      ? chatOptions.allowed
      : undefined;

  // An edit in an existing chat updates the store's edits from the store's
  // current state, so edits made back to back each see the one before.
  // Until the chat's details load the edit is dropped: built on nothing, it
  // would overwrite the saved choice.
  const editChat = useCallback(
    (
      change: (current: ChatConfiguration) => Partial<ChatToolOptions> | null
    ) => {
      if (
        chatSessionId === null ||
        activeAgent === undefined ||
        integrationIds === null
      ) {
        return;
      }
      const store = useChatSessionStore.getState();
      const session = store.sessions.get(chatSessionId);
      const options = effectiveOptions(
        session?.toolOptions,
        session?.toolOptionsEdits
      );
      if (options === undefined) return;
      const fields = change(
        configurationFrom(
          options,
          activeAgent.tools,
          integrationIds,
          preferredIntegrations ?? {}
        )
      );
      if (fields === null) return;
      store.updateSessionData(chatSessionId, {
        toolOptionsEdits: { ...session?.toolOptionsEdits, ...fields },
      });
    },
    [chatSessionId, activeAgent, integrationIds, preferredIntegrations]
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
          return tools === current.tools ||
            activeAgent === undefined ||
            integrationIds === null
            ? null
            : toolFields(
                withTools(current, tools),
                activeAgent,
                integrationIds
              );
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
        return { key, configuration: withTools(current, tools) };
      });
    },
    [key, editChat, activeAgent, integrationIds]
  );

  const { setIntegrationsDisabled } = preferences;
  const setIntegrationEnabled = useCallback(
    (ids: readonly number[], enabled: boolean) => {
      if (key === null || configAgentId === undefined) return;
      if (signedIn)
        setIntegrationsDisabled(configAgentId, ids, !enabled).catch(() =>
          toast.error(t("toolsPopover.selectionSaveFailed"))
        );
      const change = (
        current: IntegrationConfiguration
      ): IntegrationConfiguration => {
        if (ids.every((id) => (current[id] === "disabled") !== enabled)) {
          return current;
        }
        const next: Record<number, "disabled"> = { ...current };
        for (const id of ids) {
          if (enabled) delete next[id];
          else next[id] = "disabled";
        }
        return next;
      };
      if (isChatKey(key)) {
        editChat((current) => {
          const integrations = change(current.integrations);
          return integrations === current.integrations ||
            activeAgent === undefined ||
            integrationIds === null
            ? null
            : toolFields(
                { ...current, integrations },
                activeAgent,
                integrationIds
              );
        });
        return;
      }
      // A signed-in user's new chat reads the saved choice instead.
      if (signedIn) return;
      setEntry((previous) => {
        if (previous.key !== key) return previous;
        const current = previous.configuration;
        const integrations = change(current.integrations);
        if (integrations === current.integrations) return previous;
        return { key, configuration: { ...current, integrations } };
      });
    },
    [
      key,
      editChat,
      activeAgent,
      configAgentId,
      integrationIds,
      signedIn,
      setIntegrationsDisabled,
      t,
    ]
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
    const preferredToolId = preferredToolIdOf(configuration.tools);
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
      preferredAction: configuration.preferredAction,
      disabledToolIds: ids.filter(
        (toolId) => configuration.tools[toolId] === "disabled"
      ),
      // An integration removed from the agent is off, so a saved action of it is
      // not sent.
      isIntegrationEnabled: (integrationId: number) =>
        (integrationIds === null || integrationIds.includes(integrationId)) &&
        configuration.integrations[integrationId] !== "disabled",
      setIntegrationEnabled,
      allowed:
        activeAgent === undefined
          ? null
          : savedAllowed !== undefined
            ? savedAllowed
            : allowedEntries(
                configuration.tools,
                configuration.integrations,
                configuration.integrationActions,
                activeAgent,
                integrationIds ?? []
              ),
      ready,
      optionsLoaded: isChat ? chatConfiguration !== null : preferences.loaded,
      filters: configuration.filters,
      setFilters,
      handOffTo,
      handOffToNewChatWith,
    };
  }, [
    configuration,
    ready,
    isChat,
    chatConfiguration,
    preferences.loaded,
    savedAllowed,
    activeAgent,
    integrationIds,
    setToolState,
    setIntegrationEnabled,
    setFilters,
    handOffTo,
    handOffToNewChatWith,
  ]);

  // Edits in an existing chat are saved on the server at once, which decides
  // whether the chat keeps them. Only a signed-in user saves.
  useEffect(() => {
    if (chatSessionId === null || !signedIn || optionsEdits === undefined) {
      return;
    }
    void saveToolOptionsEdits(chatSessionId, () =>
      toast.error(t("toolsPopover.selectionSaveFailed"))
    );
  }, [chatSessionId, signedIn, optionsEdits, t]);

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
