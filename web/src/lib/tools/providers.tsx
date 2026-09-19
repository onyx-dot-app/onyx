"use client";

import { useCallback, useMemo } from "react";
import { createSharedHook } from "@opal/hooks";
import { MinimalAgent } from "@/lib/agents/types";
import { useAvailableSources } from "@/lib/connectors/hooks";
import {
  agentDeclaresOwnSources,
  effectiveAvailableSourcesFor,
  toggleSourceSelection,
} from "@/lib/searchFilters/utils";
import { getConfiguredSources } from "@/lib/sources";
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
  /** Pins a tool for the next message, or releases it. */
  toggleForced: (toolId: number) => void;
  /** Switches a tool off for this chat, or back on. */
  toggleEnabled: (toolId: number) => void;
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
 * The tool states and the source selection are orthogonal axes: forcing,
 * enabling or disabling a tool never changes which sources are selected, and
 * picking sources never changes any tool's state. Both live on the chat's
 * {@link ToolConfigurationHandle}, where a new chat starts untouched — every
 * source on.
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
  const { availableSources, settled } = useAvailableSources();
  // Source edits materialise and normalize against the configured roster, so
  // they wait for it to be complete (stale allowed): an edit against a
  // half-fetched list would freeze a partial selection into the chat. An
  // agent declaring its own knowledge_sources carries its complete roster
  // and never waits on the workspace connector fetch.
  const sourcesSettled = settled || agentDeclaresOwnSources(agent);

  const effectiveAvailableSources = useMemo<ValidSources[]>(
    () => effectiveAvailableSourcesFor(agent, availableSources),
    [agent, availableSources]
  );

  const configuredSources = useMemo(
    () => getConfiguredSources(effectiveAvailableSources),
    [effectiveAvailableSources]
  );

  const { filters, setFilters } = toolConfiguration;

  const isSourceEnabled = useCallback(
    (uniqueKey: string) =>
      filters.selectedSources === null ||
      filters.selectedSources.includes(uniqueKey),
    [filters.selectedSources]
  );

  const enabledSourceCount = configuredSources.filter((source) =>
    isSourceEnabled(source.uniqueKey)
  ).length;

  const toggleForced = useCallback(
    (toolId: number) => toolConfiguration.toggleToolState(toolId, "forced"),
    [toolConfiguration]
  );

  const toggleEnabled = useCallback(
    (toolId: number) => toolConfiguration.toggleToolState(toolId, "disabled"),
    [toolConfiguration]
  );

  const toggleSource = useCallback(
    (uniqueKey: string) => {
      if (!sourcesSettled) return;
      setFilters((current) => ({
        ...current,
        selectedSources: toggleSourceSelection(
          current.selectedSources,
          uniqueKey,
          configuredSources.map((source) => source.uniqueKey)
        ),
      }));
    },
    [sourcesSettled, configuredSources, setFilters]
  );

  // Back to the untouched default rather than a frozen full roster, so a
  // connector added later is on, the same as in a chat never edited.
  const enableAllSources = useCallback(() => {
    if (!sourcesSettled) return;
    setFilters((current) =>
      current.selectedSources === null
        ? current
        : { ...current, selectedSources: null }
    );
  }, [sourcesSettled, setFilters]);

  const disableAllSources = useCallback(() => {
    if (!sourcesSettled) return;
    setFilters((current) => ({ ...current, selectedSources: [] }));
  }, [sourcesSettled, setFilters]);

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
