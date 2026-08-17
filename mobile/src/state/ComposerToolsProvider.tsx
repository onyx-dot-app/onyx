/*
 * State lives in a hook, not the provider: ChatSurface both hosts the provider and calls
 * `resolveToolOptions()` at send time, and a component can't read a context it provides.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { useWorkspaceSettings } from "@/api/settings";
import type { ChatToolOptions } from "@/api/chat/stream";
import { DEFAULT_AGENT_ID, type MinimalAgent } from "@/chat/agents";
import {
  buildInternalSearchFilters,
  configuredSources,
  type DocumentSource,
} from "@/chat/sources";
import {
  computeAllowedToolIds,
  displayableTools,
  hasSearchToolsAvailable,
  isSearchTool,
  type ToolSnapshot,
} from "@/chat/tools";
import { useAgentPreferences } from "@/hooks/useAgentPreferences";
import { useConnectorSources } from "@/hooks/useConnectorSources";
import { useDeepResearchToggle } from "@/hooks/useDeepResearchToggle";
import { useForcedTools } from "@/hooks/useForcedTools";
import { useSourceSelection } from "@/hooks/useSourceSelection";

const NO_TOOLS: ToolSnapshot[] = [];
const NO_IDS: number[] = [];
const NO_SOURCES: DocumentSource[] = [];

export interface ComposerTools {
  showDeepResearch: boolean;
  deepResearchEnabled: boolean;
  toggleDeepResearch: () => void;
  actionTools: ToolSnapshot[];
  forcedToolId: number | null;
  toggleForcedTool: (toolId: number) => void;
  disabledToolIds: number[];
  toggleToolEnabled: (toolId: number) => void;
  sourceToolId: number | null;
  sourceOptions: DocumentSource[];
  enabledSourceCount: number;
  isSourceEnabled: (source: DocumentSource) => boolean;
  toggleSource: (source: DocumentSource) => void;
  enableAllSources: () => void;
  disableAllSources: () => void;
  // Report the agent a send used, once that send is known to have created the session.
  notePendingSend: (agentForSend: MinimalAgent | null) => void;
  // Read at send time, never during render.
  resolveToolOptions: () => ChatToolOptions;
}

interface ComposerToolsInputs {
  chatSessionId: string | null;
  agent: MinimalAgent | null;
  /*
   * Deep research is unsupported in projects (web hides it too — ENG-3818). Only the project
   * landing composer is detectable: a chat opened from a project has no project id on the wire.
   */
  isProjectWorkflow: boolean;
  // Crossing this boundary releases a forced tool.
  projectId: number | null;
}

export function useComposerToolsState({
  chatSessionId,
  agent,
  isProjectWorkflow,
  projectId,
}: ComposerToolsInputs): ComposerTools {
  const { settings } = useWorkspaceSettings();
  const agentId = agent?.id;

  const { deepResearchEnabled, toggleDeepResearch } = useDeepResearchToggle({
    chatSessionId,
    agentId,
  });
  const { forcedToolId, toggleForcedTool, forceTool, clearForcedTool } =
    useForcedTools({
      chatSessionId,
      agentId,
      projectId,
    });
  const {
    isLoaded: preferencesLoaded,
    disabledToolIdsFor,
    setToolDisabled,
  } = useAgentPreferences();

  /*
   * `agent` goes null for a beat after a send, before the new session reaches the sessions list.
   * Hold the last one, or the menu vanishes and the send re-allows tools the user switched off.
   * The hold adopts a pending send's agent so switching agents mid-create can't rewrite what the
   * finished session runs on. Set during render, not an effect, so it's right on the first render
   * that loses the agent; compared by id so a caller that rebuilds the agent object can't loop.
   */
  const [pendingSend, setPendingSend] = useState<{
    agent: MinimalAgent | null;
  } | null>(null);
  const [held, setHeld] = useState<{
    agent: MinimalAgent | null;
    sessionId: string | null;
  }>({ agent, sessionId: chatSessionId });
  if (
    agent &&
    (held.agent?.id !== agent.id || held.sessionId !== chatSessionId)
  ) {
    setHeld({ agent, sessionId: chatSessionId });
  } else if (
    !agent &&
    pendingSend &&
    held.sessionId === null &&
    chatSessionId !== null
  ) {
    setHeld({ agent: pendingSend.agent, sessionId: chatSessionId });
    setPendingSend(null);
  }
  const effectiveAgent =
    agent ?? (held.sessionId === chatSessionId ? held.agent : null);
  const effectiveAgentId = effectiveAgent?.id;

  // With no agent resolved yet, don't withdraw a control the user just used.
  const canSearch = effectiveAgent
    ? hasSearchToolsAvailable(effectiveAgent.tools)
    : deepResearchEnabled;
  const showDeepResearch =
    !isProjectWorkflow && settings.deep_research_enabled && canSearch;

  const actionTools = useMemo(
    () => (effectiveAgent ? displayableTools(effectiveAgent.tools) : NO_TOOLS),
    [effectiveAgent],
  );

  const disabledToolIds = useMemo(
    () =>
      effectiveAgentId == null ? NO_IDS : disabledToolIdsFor(effectiveAgentId),
    [effectiveAgentId, disabledToolIdsFor],
  );

  // Inert in a project: a connector-type filter would exclude the project's own files.
  const sourcesManaged = !isProjectWorkflow;

  const searchTool = useMemo(
    () => actionTools.find(isSearchTool) ?? null,
    [actionTools],
  );
  const sourceToolId = sourcesManaged ? (searchTool?.id ?? null) : null;

  const { sources: connectorSources } = useConnectorSources();

  // No declared `knowledge_sources` means "everything accessible", not "nothing".
  const agentSourceScope = useMemo(() => {
    if (!effectiveAgent || !sourcesManaged) return NO_SOURCES;
    if (effectiveAgent.id === DEFAULT_AGENT_ID) return connectorSources;
    const declared = effectiveAgent.knowledge_sources ?? NO_SOURCES;
    if (declared.length === 0 && effectiveAgent.tools.some(isSearchTool)) {
      return connectorSources;
    }
    return declared;
  }, [connectorSources, effectiveAgent, sourcesManaged]);

  const sourceOptions = useMemo(
    () => configuredSources(agentSourceScope),
    [agentSourceScope],
  );

  const {
    selectedSources,
    initialized: sourcesInitialized,
    isSourceEnabled,
    toggleSource: toggleSourceSelection,
    setSources,
    enableAllSources: enableAllSourceSelection,
    disableAllSources: disableAllSourceSelection,
  } = useSourceSelection(sourceOptions);

  const enabledSourceCount = useMemo(
    () => sourceOptions.filter(isSourceEnabled).length,
    [isSourceEnabled, sourceOptions],
  );

  const applyToolDisabled = useCallback(
    (toolId: number, disabled: boolean): Promise<void> => {
      const currentAgentId = effectiveAgentId;
      if (currentAgentId == null) return Promise.resolve();
      // The backend fails the turn when the forced tool isn't among the constructed ones.
      if (disabled && forcedToolId === toolId) clearForcedTool();
      return setToolDisabled(currentAgentId, toolId, disabled);
    },
    [clearForcedTool, effectiveAgentId, forcedToolId, setToolDisabled],
  );

  /*
   * Search follows the sources: with all of them off it could only come back empty.
   *
   * Single writer. Mobile's preference writes settle after an await, so a handler and this effect
   * would both act on the same stale "still enabled" and cancel out. Releasing the flag on settle
   * lets the resulting cache update — or rollback — re-run the effect, so a failed write retries.
   *
   * Held per agent, not as a bare flag: preferences are per agent, so a write for one can't
   * confuse a reconcile for another. Blocking on it would, because clearing a ref re-renders
   * nothing — the agent switched into would sit unreconciled until an unrelated render.
   */
  const preferenceWriteAgentId = useRef<number | null>(null);
  /*
   * The first reconcile of an (agent, catalogue) pair runs backwards: a switched-off search is a
   * deliberate, server-persisted choice, while the sources it meets are only the picker's
   * "everything" default — so it clears them instead. Afterwards, sources drive.
   */
  const adopted = useRef<string | null>(null);
  useEffect(() => {
    if (sourceToolId == null || !sourcesInitialized) return;
    if (effectiveAgentId == null) return;
    // Before the record loads, "nothing disabled" is a default, not an observation.
    if (!preferencesLoaded) return;
    if (preferenceWriteAgentId.current === effectiveAgentId) return;

    const searchDisabled = disabledToolIds.includes(sourceToolId);
    const scope = `${effectiveAgentId}:${sourceOptions.join(",")}`;
    if (adopted.current !== scope) {
      adopted.current = scope;
      if (searchDisabled && enabledSourceCount > 0) {
        disableAllSourceSelection();
        return;
      }
    }

    const wanted = enabledSourceCount > 0;
    if (wanted === !searchDisabled) return;
    const writingAgentId = effectiveAgentId;
    preferenceWriteAgentId.current = writingAgentId;
    void applyToolDisabled(sourceToolId, !wanted).finally(() => {
      // Only if a later write for another agent hasn't taken the slot.
      if (preferenceWriteAgentId.current === writingAgentId) {
        preferenceWriteAgentId.current = null;
      }
    });
  }, [
    applyToolDisabled,
    disableAllSourceSelection,
    disabledToolIds,
    effectiveAgentId,
    enabledSourceCount,
    preferencesLoaded,
    sourceOptions,
    sourcesInitialized,
    sourceToolId,
  ]);

  // Restored when search returns, so the round trip doesn't widen a partial pick to everything.
  const sourcesBeforeSearchOff = useRef<DocumentSource[]>(NO_SOURCES);

  const toggleToolEnabled = useCallback(
    (toolId: number) => {
      const wasDisabled = disabledToolIds.includes(toolId);
      const write = applyToolDisabled(toolId, !wasDisabled);
      if (toolId !== sourceToolId) return;
      /*
       * The effect sees the sources cleared below before it sees this write, so without the flag
       * it would issue the opposite one.
       */
      const writingAgentId = effectiveAgentId ?? null;
      preferenceWriteAgentId.current = writingAgentId;
      void write.finally(() => {
        if (preferenceWriteAgentId.current === writingAgentId) {
          preferenceWriteAgentId.current = null;
        }
      });
      if (wasDisabled) {
        /*
         * The park outlives the agent it was made under: restoring a source this one can't reach
         * would leave search on with nothing enabled.
         */
        const previous = sourcesBeforeSearchOff.current.filter((source) =>
          sourceOptions.includes(source),
        );
        if (previous.length > 0) setSources(previous);
        else enableAllSourceSelection();
        sourcesBeforeSearchOff.current = NO_SOURCES;
      } else {
        sourcesBeforeSearchOff.current = selectedSources;
        disableAllSourceSelection();
      }
    },
    [
      applyToolDisabled,
      disableAllSourceSelection,
      disabledToolIds,
      effectiveAgentId,
      enableAllSourceSelection,
      selectedSources,
      setSources,
      sourceOptions,
      sourceToolId,
    ],
  );

  // Picking a source is a statement about search, so it pins search for the next turn.
  const toggleSource = useCallback(
    (source: DocumentSource) => {
      const wasEnabled = isSourceEnabled(source);
      toggleSourceSelection(source);
      if (sourceToolId == null) return;
      if (!wasEnabled) {
        forceTool(sourceToolId);
      } else if (enabledSourceCount <= 1 && forcedToolId === sourceToolId) {
        clearForcedTool();
      }
    },
    [
      clearForcedTool,
      enabledSourceCount,
      forceTool,
      forcedToolId,
      isSourceEnabled,
      sourceToolId,
      toggleSourceSelection,
    ],
  );

  const enableAllSources = useCallback(() => {
    enableAllSourceSelection();
    if (sourceToolId != null) forceTool(sourceToolId);
  }, [enableAllSourceSelection, forceTool, sourceToolId]);

  const disableAllSources = useCallback(() => {
    disableAllSourceSelection();
    if (sourceToolId != null && forcedToolId === sourceToolId) {
      clearForcedTool();
    }
  }, [clearForcedTool, disableAllSourceSelection, forcedToolId, sourceToolId]);

  const notePendingSend = useCallback(
    (agentForSend: MinimalAgent | null) =>
      setPendingSend({ agent: agentForSend }),
    [],
  );

  return useMemo(
    () => ({
      showDeepResearch,
      deepResearchEnabled,
      toggleDeepResearch,
      actionTools,
      forcedToolId,
      /*
       * Unwrapped: the effect already keeps "search on" and "some source on" equivalent. Web
       * re-enables every source here instead, which discards a partial selection.
       */
      toggleForcedTool,
      disabledToolIds,
      toggleToolEnabled,
      sourceToolId,
      sourceOptions,
      enabledSourceCount,
      isSourceEnabled,
      toggleSource,
      enableAllSources,
      disableAllSources,
      notePendingSend,
      // Gated on `showDeepResearch` so a control the admin has since hidden can't send true.
      resolveToolOptions: () => {
        /*
         * The FULL tool list, not the displayed rows: omitting the ones the menu hides (File
         * Reader, MCP) strips them server-side as soon as any tool is off.
         */
        const allowedToolIds = effectiveAgent
          ? computeAllowedToolIds(effectiveAgent.tools, disabledToolIds)
          : null;
        // A forced id that's filtered out, or belongs to another agent, fails the turn mid-stream.
        const forcedIsSendable =
          forcedToolId != null &&
          !disabledToolIds.includes(forcedToolId) &&
          (effectiveAgent?.tools.some((tool) => tool.id === forcedToolId) ??
            false);

        return {
          deepResearch: showDeepResearch && deepResearchEnabled,
          allowedToolIds,
          forcedToolId: forcedIsSendable ? forcedToolId : null,
          /*
           * Only the sources still on the menu: a stale pick from a wider agent would narrow the
           * search to something this one can't reach.
           */
          internalSearchFilters: buildInternalSearchFilters(
            sourceOptions.filter(isSourceEnabled),
          ),
        };
      },
    }),
    [
      effectiveAgent,
      showDeepResearch,
      deepResearchEnabled,
      toggleDeepResearch,
      actionTools,
      forcedToolId,
      toggleForcedTool,
      disabledToolIds,
      toggleToolEnabled,
      sourceToolId,
      sourceOptions,
      enabledSourceCount,
      isSourceEnabled,
      toggleSource,
      enableAllSources,
      disableAllSources,
      notePendingSend,
    ],
  );
}

const ComposerToolsContext = createContext<ComposerTools | undefined>(
  undefined,
);

interface ComposerToolsProviderProps {
  value: ComposerTools;
  children: ReactNode;
}

export function ComposerToolsProvider({
  value,
  children,
}: ComposerToolsProviderProps) {
  return (
    <ComposerToolsContext.Provider value={value}>
      {children}
    </ComposerToolsContext.Provider>
  );
}

export function useComposerTools(): ComposerTools {
  const tools = useContext(ComposerToolsContext);
  if (!tools) {
    throw new Error(
      "useComposerTools must be used within a ComposerToolsProvider",
    );
  }
  return tools;
}
