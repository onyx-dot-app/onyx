import { useMemo, useState } from "react";
import { Dimensions, Pressable, ScrollView, View } from "react-native";

import { Popover, Text } from "@/components/opal";
import { ActionLineItem } from "@/components/chat/actions/ActionLineItem";
import { SwitchList } from "@/components/chat/actions/SwitchList";
import { toSourceItem } from "@/components/chat/actions/SourceRow";
import { usePopoverPlacement } from "@/components/chat/usePopoverPlacement";
import { SvgChevronLeft } from "@/components/icons/SvgChevronLeft";
import { SvgSliders } from "@/components/icons/SvgSliders";
import { SEARCH_TOOL_ID } from "@/lib/constants";
import type { MinimalAgent } from "@/lib/types/agents";
import { useForcedTools } from "@/state/useForcedTools";
import { useTools } from "@/query/tools";
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
// AVAILABILITY MODEL (web parity): tools have NO per-tool enable switch. A tool
// is shown greyed/disabled when UNAVAILABLE and normal when available; a tool is
// available iff its id is in the GLOBAL tool registry (`useTools` -> GET /tool).
// The search tool is NEVER unavailable. Tapping an available non-search tool
// FORCES it (toggleForcedTool). Only SOURCES keep enable/disable switches (in
// the sources sub-view).
//
// SOURCE <-> SEARCH FORCE COUPLING (ported from web): enabling the FIRST source
// force-pins the Search tool (toggleForcedTool); disabling the LAST source
// un-forces it. This is how the Search tool gets forced. Guarded on the search
// tool being present on the agent.
// ---------------------------------------------------------------------------

interface ActionsPopoverProps {
  /** The agent whose tools + sources this popover manages. */
  agent: MinimalAgent;
  /** The persona id (retained for parity with the chat surface API). */
  personaId: number;
}

type SecondaryView = null | "sources";

export function ActionsPopover({ agent }: ActionsPopoverProps) {
  const { insets, contentWidth } = usePopoverPlacement({
    maxWidth: 256,
    widthMargin: 48,
  });
  const [secondaryView, setSecondaryView] = useState<SecondaryView>(null);

  // --- force-tool (ephemeral) ---------------------------------------------
  const forcedToolIds = useForcedTools((s) => s.forcedToolIds);
  const toggleForcedTool = useForcedTools((s) => s.toggleForcedTool);

  // --- global tool registry (availability) --------------------------------
  // A tool is available iff its id is in this set (web parity: useAvailableTools).
  const { data: availableTools } = useTools();
  const availableToolIdSet = useMemo(
    () => new Set((availableTools ?? []).map((t) => t.id)),
    [availableTools]
  );

  // --- source prefs (MMKV) -------------------------------------------------
  const availableSourceStrings = useAvailableSourceStrings();
  const { configuredSources, isSourceEnabled, toggleSource } =
    useSourcePreferences(availableSourceStrings);

  // --- search tool identity (string in_code_tool_id -> numeric id) ---------
  const searchTool = useMemo(
    () => agent.tools.find((t) => t.in_code_tool_id === SEARCH_TOOL_ID),
    [agent.tools]
  );
  const searchToolId = searchTool?.id;

  // Exclude MCP tools: MCP is out of scope for this feature (web parity).
  const displayTools = useMemo(
    () => agent.tools.filter((t) => t.chat_selectable && !t.mcp_server_id),
    [agent.tools]
  );

  const enabledSourceCount = configuredSources.filter((s) =>
    isSourceEnabled(s.uniqueKey)
  ).length;
  const totalSourceCount = configuredSources.length;

  function handleSourceToggle(key: string) {
    const willEnable = !isSourceEnabled(key);
    const newEnabledCount = enabledSourceCount + (willEnable ? 1 : -1);

    toggleSource(key);

    // Source -> force-search coupling: first source force-pins Search; last
    // source un-forces it. Guarded on the search tool being present.
    if (searchToolId !== undefined) {
      if (willEnable && !forcedToolIds.includes(searchToolId)) {
        toggleForcedTool(searchToolId);
      } else if (
        newEnabledCount === 0 &&
        forcedToolIds.includes(searchToolId)
      ) {
        toggleForcedTool(searchToolId);
      }
    }
  }

  function handleOpenChange(next: boolean) {
    // Always start on the primary (tool list) view when (re)opening.
    if (next) setSecondaryView(null);
  }

  const screenHeight = Dimensions.get("window").height;
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
          <SvgSliders size={18} color="text-04" />
        </Pressable>
      </Popover.Trigger>

      <Popover.Content
        side="top"
        align="start"
        sideOffset={8}
        insets={insets}
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
              <SvgChevronLeft size={16} color="text-03" />
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
                const isUnavailable =
                  !availableToolIdSet.has(tool.id) &&
                  tool.in_code_tool_id !== SEARCH_TOOL_ID;
                return (
                  <ActionLineItem
                    key={tool.id}
                    tool={tool}
                    isForced={forcedToolIds.includes(tool.id)}
                    isUnavailable={isUnavailable}
                    onToggleForced={() => toggleForcedTool(tool.id)}
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
