"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";
import { createSharedHook } from "@opal/hooks";

import { MinimalAgent } from "@/lib/agents/types";
import { isAssistant } from "@/lib/agents/utils";
import { useAvailableSources } from "@/lib/connectors/hooks";
import { SourceMetadata } from "@/lib/search/interfaces";
import { getConfiguredSources } from "@/lib/sources";
import { useProjectsContext } from "@/lib/projects/providers";
import { useSourcePreferences } from "@/lib/searchFilters/hooks";
import { useSharedSearchFilters } from "@/lib/searchFilters/providers";
import { SEARCH_TOOL_ID } from "@/lib/tools/constants";
import type { ToolConfigurationHandle } from "@/lib/tools/hooks";
import { ValidSources } from "@/lib/types";

/** A source the picker can show: {@link getConfiguredSources} guarantees a key. */
type ConfiguredSource = ReturnType<typeof getConfiguredSources>[number];

interface ToolsPopoverInputs {
  /**
   * The agent every row acts on. Passed in rather than resolved, because the
   * agent viewer's popover acts on an agent that is not the active one.
   */
  agent: MinimalAgent;
  /**
   * Owned by the surface, because the send path reads the same one. A second
   * `useToolConfiguration` would hold its own state and never reach the send.
   */
  toolConfiguration: ToolConfigurationHandle;
  /** Drills the popover into its sources sub-view. */
  openSources: () => void;
  /** Dismisses the popover. */
  close: () => void;
}

export interface ToolsPopoverValue extends ToolsPopoverInputs {
  /** Every source this agent can search over. */
  configuredSources: ConfiguredSource[];
  /** How many of {@link configuredSources} are on, and how many there are. */
  sourceCounts: { enabled: number; total: number };
  isSourceEnabled: (uniqueKey: string) => boolean;
  /**
   * Pins a tool for the next message, or releases it. Pinning internal search
   * widens the sources, since a pin with nothing selected finds nothing.
   */
  toggleForced: (toolId: number) => void;
  /**
   * Switches a tool off for this chat, or back on. Internal search parks its
   * sources on the way off and restores them on the way back.
   */
  toggleEnabled: (toolId: number) => void;
  /** Picking a source is a statement about search, so it pins search too. */
  toggleSource: (uniqueKey: string) => void;
  enableAllSources: () => void;
  disableAllSources: () => void;
}

/**
 * What the tools popover and every row inside it read.
 *
 * The rows are the reason this exists. Each one needs the agent, the chat's
 * tool configuration and the source counts, and none of those can be rebuilt
 * inside a row — so without a shared instance they arrive as props on every
 * row, which is the shape this replaces. Everything a row can resolve on its
 * own (permissions, the configured tools, the connectors) stays a hook call in
 * the row.
 *
 * Mirrors mobile's `useComposerToolsState`, which solves the same problem for
 * the same feature.
 */
function useToolsPopoverState({
  agent,
  toolConfiguration,
  openSources,
  close,
}: ToolsPopoverInputs): ToolsPopoverValue {
  const {
    availableSources,
    isLoading: sourcesLoading,
    error: sourcesError,
  } = useAvailableSources();
  const { selectedSources, setSelectedSources } = useSharedSearchFilters();
  const { currentProjectId } = useProjectsContext();
  const inProject = currentProjectId != null;

  // A partial list must not become the user's persisted choice, but it is
  // still worth showing. Only initialisation waits for the fetch to settle.
  const sourcesReady = !sourcesLoading && !sourcesError;

  const hasSearchTool = agent.tools.some(
    (tool) => tool.in_code_tool_id === SEARCH_TOOL_ID
  );

  // `knowledge_sources` is the complete set this agent can search over. Empty
  // on a searching agent means "everything accessible", not "nothing".
  const effectiveAvailableSources = useMemo<ValidSources[]>(() => {
    if (isAssistant(agent)) return availableSources;
    const declared = agent.knowledge_sources ?? [];
    if (declared.length === 0 && hasSearchTool) return availableSources;
    return declared as ValidSources[];
  }, [agent, availableSources, hasSearchTool]);

  const {
    sourcesInitialized,
    enableSources,
    enableAllSources: baseEnableAllSources,
    disableAllSources: baseDisableAllSources,
    toggleSource: baseToggleSource,
    isSourceEnabled,
  } = useSourcePreferences({
    availableSources: effectiveAvailableSources,
    selectedSources,
    setSelectedSources,
    ready: sourcesReady,
  });

  const configuredSources = useMemo(
    () => getConfiguredSources(effectiveAvailableSources),
    [effectiveAvailableSources]
  );

  const enabledSourceCount = configuredSources.filter((source) =>
    isSourceEnabled(source.uniqueKey)
  ).length;

  const searchToolId =
    agent.tools.find(
      (tool) => tool.in_code_tool_id === SEARCH_TOOL_ID && !tool.mcp_server_id
    )?.id ?? null;

  const setSearchToolEnabled = useCallback(
    (enabled: boolean) => {
      if (searchToolId === null) return;
      toolConfiguration.setToolState(searchToolId, () =>
        enabled ? null : "disabled"
      );
    },
    [searchToolId, toolConfiguration]
  );

  // Searching nothing returns nothing, so the search tool follows whether any
  // source is selected.
  useEffect(() => {
    if (searchToolId === null || !sourcesInitialized) return;
    // Inside a project the tool searches that project's files, so the
    // connector sources say nothing about whether it should be on.
    if (inProject) return;
    setSearchToolEnabled(enabledSourceCount > 0);
  }, [
    searchToolId,
    enabledSourceCount,
    sourcesInitialized,
    setSearchToolEnabled,
    inProject,
  ]);

  const toggleForced = useCallback(
    (toolId: number) => {
      const wasForced = toolConfiguration.forcedToolId === toolId;
      if (!wasForced && toolId === searchToolId) {
        setSelectedSources(configuredSources);
      }
      toolConfiguration.toggleToolState(toolId, "forced");
    },
    [configuredSources, searchToolId, setSelectedSources, toolConfiguration]
  );

  // Restored when search returns, so the round trip does not widen a partial
  // pick back out to everything.
  const parkedSources = useRef<SourceMetadata[]>([]);

  const toggleEnabled = useCallback(
    (toolId: number) => {
      const wasDisabled = toolConfiguration.disabledToolIds.includes(toolId);
      toolConfiguration.toggleToolState(toolId, "disabled");
      if (toolId !== searchToolId) return;

      if (wasDisabled) {
        if (parkedSources.current.length > 0) {
          enableSources(parkedSources.current);
        } else {
          baseEnableAllSources();
        }
        parkedSources.current = [];
      } else {
        parkedSources.current = [...selectedSources];
        baseDisableAllSources();
      }
    },
    [
      baseDisableAllSources,
      baseEnableAllSources,
      enableSources,
      searchToolId,
      selectedSources,
      toolConfiguration,
    ]
  );

  const pinSearch = useCallback(() => {
    if (searchToolId === null) return;
    // Toggling the already-pinned tool would release it, so only fire when it
    // is not the pinned one.
    if (toolConfiguration.forcedToolId !== searchToolId) {
      toolConfiguration.toggleToolState(searchToolId, "forced");
    }
  }, [searchToolId, toolConfiguration]);

  const releaseSearch = useCallback(() => {
    if (
      searchToolId !== null &&
      toolConfiguration.forcedToolId === searchToolId
    ) {
      toolConfiguration.clearForcedTool();
    }
  }, [searchToolId, toolConfiguration]);

  const enableAllSources = useCallback(() => {
    // Through the preferences hook, so the choice persists the way
    // disabling all already does.
    baseEnableAllSources();
    setSearchToolEnabled(true);
    pinSearch();
  }, [baseEnableAllSources, pinSearch, setSearchToolEnabled]);

  const disableAllSources = useCallback(() => {
    baseDisableAllSources();
    setSearchToolEnabled(false);
    releaseSearch();
  }, [baseDisableAllSources, releaseSearch, setSearchToolEnabled]);

  const toggleSource = useCallback(
    (uniqueKey: string) => {
      const wasEnabled = isSourceEnabled(uniqueKey);
      baseToggleSource(uniqueKey);
      setSearchToolEnabled(enabledSourceCount + (wasEnabled ? -1 : 1) > 0);

      if (!wasEnabled) {
        pinSearch();
        return;
      }
      // The last source going off leaves nothing to search, so the pin goes
      // with it.
      const stillOn = configuredSources.some(
        (source) =>
          source.uniqueKey !== uniqueKey && isSourceEnabled(source.uniqueKey)
      );
      if (!stillOn) releaseSearch();
    },
    [
      baseToggleSource,
      configuredSources,
      enabledSourceCount,
      isSourceEnabled,
      pinSearch,
      releaseSearch,
      setSearchToolEnabled,
    ]
  );

  return useMemo(
    () => ({
      agent,
      toolConfiguration,
      openSources,
      close,
      configuredSources,
      sourceCounts: {
        enabled: enabledSourceCount,
        total: configuredSources.length,
      },
      isSourceEnabled,
      toggleForced,
      toggleEnabled,
      toggleSource,
      enableAllSources,
      disableAllSources,
    }),
    [
      agent,
      close,
      configuredSources,
      disableAllSources,
      enableAllSources,
      enabledSourceCount,
      isSourceEnabled,
      openSources,
      toggleEnabled,
      toggleForced,
      toggleSource,
      toolConfiguration,
    ]
  );
}

export const [ToolsPopoverProvider, useToolsPopover] = createSharedHook(
  useToolsPopoverState,
  "ToolsPopover"
);
