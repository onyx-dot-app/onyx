import { useMemo, useRef, useState } from "react";
import { Dimensions, Pressable, ScrollView, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Popover, Text } from "@/components/opal";
import { ActionLineItem } from "@/components/chat/actions/ActionLineItem";
import { SwitchList } from "@/components/chat/actions/SwitchList";
import { toSourceItem } from "@/components/chat/actions/SourceRow";
import { ChevronLeftIcon, SlidersIcon } from "@/components/ui/icons";
import { useToken } from "@/theme/ThemeProvider";
import { SEARCH_TOOL_ID } from "@/lib/constants";
import type { MinimalAgent } from "@/lib/types/agents";
import type { MobileSource } from "@/lib/sources/sourceMetadata";
import { useForcedTools } from "@/state/useForcedTools";
import {
  useAgentPreferences,
  useUpdateAgentPreference,
} from "@/query/agentPreferences";
import { useAvailableSourceStrings } from "@/query/connectors";
import { useSourcePreferences } from "@/lib/sources/useSourcePreferences";

// ---------------------------------------------------------------------------
// ActionsPopover — the sliders trigger + anchored popover that hosts the tool
// list and a nested sources sub-view (web parity: ActionsPopover/index.tsx).
//
// It renders its OWN trigger (a sliders Pressable, mirroring the AttachMenu /
// ModelSelectorTrigger opal-Popover usage), so callers just pass `agent` +
// `personaId`. Requires a <PortalHost/> near the app root (present in
// app/_layout.tsx).
//
// Three independent state layers feed the rows:
//   - force-tool      → useForcedTools (ephemeral zustand; max one forced tool)
//   - tool enable/dis → useAgentPreferences + useUpdateAgentPreference
//                       (backend disabled_tool_ids, optimistic)
//   - source prefs    → useSourcePreferences (MMKV)
//
// SOURCE <-> SEARCH COUPLING (ported from web, adapted to mobile hooks):
//   1. Enabling the FIRST source force-pins Search (toggleForcedTool); disabling
//      the LAST source un-forces it (toggleForcedTool when search is the forced
//      tool).
//   2. Toggling a source keeps Search ENABLED (not in disabled_tool_ids) while
//      >=1 source is on, and disabled when 0 are on (web setSearchToolEnabled).
//   3. Toggling the Search tool OFF stashes the currently-enabled sources (ref)
//      then disableAllSources(); toggling ON restores the stash (or
//      enableAllSources() if none stashed).
//   4. Force-pinning Search while 0 sources are enabled opens the sources
//      sub-view so the user can pick sources.
//
// DIVERGENCE FROM WEB: mobile couples the Search tool <-> sources ONLY on user
// toggle. Unlike web, it intentionally does NOT run a mount-time reconciliation
// effect (which would side-effect backend mutations on mount), so cross-mount /
// cross-platform drift (e.g. enabled-search + 0-sources) is tolerated; the
// send-path filter computation is the safety net.
// ---------------------------------------------------------------------------

interface ActionsPopoverProps {
  /** The agent whose tools + sources this popover manages. */
  agent: MinimalAgent;
  /** The persona id used to read/write tool enable/disable preferences. */
  personaId: number;
}

type SecondaryView = null | "sources";

export function ActionsPopover({ agent, personaId }: ActionsPopoverProps) {
  const insets = useSafeAreaInsets();
  const [secondaryView, setSecondaryView] = useState<SecondaryView>(null);

  const triggerColor = useToken("text-04");
  const backColor = useToken("text-03");

  // --- force-tool (ephemeral) ---------------------------------------------
  const forcedToolIds = useForcedTools((s) => s.forcedToolIds);
  const toggleForcedTool = useForcedTools((s) => s.toggleForcedTool);

  // --- tool enable/disable (backend-persisted) ----------------------------
  const { data: agentPrefs } = useAgentPreferences();
  const updateMutation = useUpdateAgentPreference();
  const disabledToolIds = agentPrefs?.[personaId]?.disabled_tool_ids ?? [];

  // --- source prefs (MMKV) -------------------------------------------------
  const availableSourceStrings = useAvailableSourceStrings();
  const {
    configuredSources,
    isSourceEnabled,
    toggleSource,
    enableAllSources,
    disableAllSources,
    enableSources,
    selectedSources,
  } = useSourcePreferences(availableSourceStrings);

  // Sources stashed when the Search tool is toggled off, restored on re-enable.
  const stashedSourcesRef = useRef<MobileSource[]>([]);

  // --- search tool identity (string in_code_tool_id -> numeric id) ---------
  const searchTool = useMemo(
    () => agent.tools.find((t) => t.in_code_tool_id === SEARCH_TOOL_ID),
    [agent.tools]
  );
  const searchToolId = searchTool?.id ?? null;

  // Exclude MCP tools: MCP is out of scope for this feature (web parity).
  const displayTools = useMemo(
    () => agent.tools.filter((t) => t.chat_selectable && !t.mcp_server_id),
    [agent.tools]
  );

  const enabledSourceCount = configuredSources.filter((s) =>
    isSourceEnabled(s.uniqueKey)
  ).length;
  const totalSourceCount = configuredSources.length;

  // --- enable/disable mutation helper -------------------------------------
  // Flip a tool's membership in disabled_tool_ids and persist (optimistic).
  function setToolDisabled(toolId: number, disabled: boolean) {
    const current = agentPrefs?.[personaId]?.disabled_tool_ids ?? [];
    const isCurrentlyDisabled = current.includes(toolId);
    if (disabled === isCurrentlyDisabled) return; // no-op
    const nextDisabled = disabled
      ? [...current, toolId]
      : current.filter((id) => id !== toolId);
    updateMutation.mutate({
      personaId,
      preference: { disabled_tool_ids: nextDisabled },
    });
  }

  function handleToggleEnabled(toolId: number) {
    const isDisabled = disabledToolIds.includes(toolId);

    // Coupling rule 3: toggling the Search tool stashes/restores sources.
    if (searchToolId !== null && toolId === searchToolId) {
      if (isDisabled) {
        // Enabling Search — restore the stashed set (or enable all if none).
        const stashed = stashedSourcesRef.current;
        if (stashed.length > 0) enableSources(stashed);
        else enableAllSources();
        stashedSourcesRef.current = [];
      } else {
        // Disabling Search — stash the currently-enabled sources, then clear.
        stashedSourcesRef.current = [...selectedSources];
        disableAllSources();
      }
    }

    // Mutual exclusion (web parity: disabling a tool UN-FORCES it): if this
    // action disables a currently-forced tool, also clear the force so it can't
    // be both forced and in disabled_tool_ids (which would trip the backend's
    // "Forced tool not found in tools" ValueError on send). toggleForcedTool
    // clears it given the max-one-forced invariant.
    const willDisable = !isDisabled;
    if (willDisable && forcedToolIds.includes(toolId)) {
      toggleForcedTool(toolId);
    }

    setToolDisabled(toolId, !isDisabled);
  }

  function handleToggleForced(toolId: number) {
    // Coupling rule 4: force-pinning Search with 0 sources opens the sub-view.
    const willForce = !forcedToolIds.includes(toolId);
    if (willForce && toolId === searchToolId && enabledSourceCount === 0) {
      setSecondaryView("sources");
    }
    // Mutual exclusion (web parity: ActionLineItem `if (disabled) onToggle()`):
    // forcing a disabled tool RE-ENABLES it first so it can't be both forced
    // and in disabled_tool_ids (which would trip the backend's "Forced tool
    // not found in tools" ValueError on send).
    if (willForce && disabledToolIds.includes(toolId)) {
      setToolDisabled(toolId, false);
    }
    toggleForcedTool(toolId);
  }

  // Mirror web setSearchToolEnabled: keep the Search tool's disabled_tool_ids
  // membership in sync with "are any sources enabled" (coupling rule 2).
  function setSearchToolEnabled(enabled: boolean) {
    if (searchToolId === null) return;
    setToolDisabled(searchToolId, !enabled);
  }

  function handleSourceToggle(uniqueKey: string) {
    const willEnable = !isSourceEnabled(uniqueKey);
    const newEnabledCount = enabledSourceCount + (willEnable ? 1 : -1);

    toggleSource(uniqueKey);

    // Coupling rule 1: first source force-pins Search; last source un-forces.
    if (searchToolId !== null) {
      if (willEnable) {
        if (!forcedToolIds.includes(searchToolId)) toggleForcedTool(searchToolId);
      } else if (
        newEnabledCount === 0 &&
        forcedToolIds.includes(searchToolId)
      ) {
        // Un-force only the search tool (correct even if the max-one-forced
        // invariant ever changes); given that invariant this clears all forcing.
        toggleForcedTool(searchToolId);
      }
    }

    // Coupling rule 2: Search enabled iff >=1 source remains on.
    setSearchToolEnabled(newEnabledCount > 0);
  }

  function handleOpenChange(next: boolean) {
    // Always start on the primary (tool list) view when (re)opening.
    if (next) setSecondaryView(null);
  }

  const screenHeight = Dimensions.get("window").height;
  const screenWidth = Dimensions.get("window").width;
  const contentWidth = Math.min(320, screenWidth - 24);
  const maxListHeight = Math.round(screenHeight * 0.5);

  const sourceItems = configuredSources.map((s) =>
    toSourceItem(s, isSourceEnabled(s.uniqueKey), () =>
      handleSourceToggle(s.uniqueKey)
    )
  );

  // Nothing selectable to show.
  if (displayTools.length === 0) return null;

  return (
    <Popover onOpenChange={handleOpenChange}>
      <Popover.Trigger asChild>
        {/* Sliders trigger — mirrors the AttachMenu / send-cluster icon button
            (h-8 w-8, rounded, active tint). */}
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Manage actions"
          hitSlop={8}
          className="h-8 w-8 items-center justify-center rounded-[8px] active:bg-background-tint-02"
        >
          <SlidersIcon size={18} color={triggerColor} />
        </Pressable>
      </Popover.Trigger>

      <Popover.Content
        side="top"
        align="start"
        sideOffset={8}
        insets={{
          top: insets.top + 8,
          bottom: insets.bottom + 8,
          left: 12,
          right: 12,
        }}
        style={{ width: contentWidth }}
      >
        {secondaryView === "sources" ? (
          <View>
            {/* Sub-view header with a back button. */}
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Back to actions"
              hitSlop={8}
              onPress={() => setSecondaryView(null)}
              className="mb-1 flex-row items-center gap-1 rounded-[8px] px-1 py-1 active:bg-background-tint-02"
            >
              <ChevronLeftIcon size={16} color={backColor} />
              <Text font="main-ui-action" color="text-05">
                Sources
              </Text>
            </Pressable>
            {sourceItems.length === 0 ? (
              <Text
                font="secondary-body"
                color="text-03"
                style={{ paddingVertical: 8, paddingHorizontal: 4 }}
              >
                No sources available
              </Text>
            ) : (
              <ScrollView
                style={{ maxHeight: maxListHeight }}
                showsVerticalScrollIndicator={false}
                keyboardShouldPersistTaps="handled"
              >
                <SwitchList items={sourceItems} />
              </ScrollView>
            )}
          </View>
        ) : (
          <View>
            <Text
              font="main-ui-action"
              color="text-05"
              style={{ paddingHorizontal: 4, paddingBottom: 8, paddingTop: 4 }}
            >
              Actions
            </Text>
            <ScrollView
              style={{ maxHeight: maxListHeight }}
              showsVerticalScrollIndicator={false}
              keyboardShouldPersistTaps="handled"
            >
              {displayTools.map((tool) => {
                const isSearchTool = tool.in_code_tool_id === SEARCH_TOOL_ID;
                return (
                  <ActionLineItem
                    key={tool.id}
                    tool={tool}
                    isForced={forcedToolIds.includes(tool.id)}
                    isDisabled={disabledToolIds.includes(tool.id)}
                    onToggleEnabled={() => handleToggleEnabled(tool.id)}
                    onToggleForced={() => handleToggleForced(tool.id)}
                    isSearchTool={isSearchTool}
                    onOpenSources={
                      isSearchTool
                        ? () => setSecondaryView("sources")
                        : undefined
                    }
                    sourceCount={
                      isSearchTool
                        ? {
                            enabled: enabledSourceCount,
                            total: totalSourceCount,
                          }
                        : undefined
                    }
                  />
                );
              })}
            </ScrollView>
          </View>
        )}
      </Popover.Content>
    </Popover>
  );
}

export default ActionsPopover;
