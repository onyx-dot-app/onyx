import { Pressable, View } from "react-native";

import { Switch, Text } from "@/components/opal";
import { ChevronRightIcon, SlidersIcon } from "@/components/ui/icons";
import { useToken } from "@/theme/ThemeProvider";
import type { ToolSnapshot } from "@/lib/types/tools";

// ---------------------------------------------------------------------------
// ActionLineItem — a single tool row in the actions popover (web parity).
//
// Behaviour (mirrors web `ActionLineItem`):
//   - Tapping the row BODY forces the tool (`onToggleForced`).
//   - For the search tool, tapping the row opens the sources sub-view
//     (`onOpenSources`) instead, and the right side shows a "<enabled> of
//     <total>" count + chevron affordance rather than a switch.
//   - The opal `Switch` on the right enables/disables the tool
//     (`onToggleEnabled`) — independent of the force tap.
//
// Visual states:
//   - forced   → label `action-link-05` + row `bg-action-link-01` (fixed bg →
//                static class, toggled conditionally),
//   - disabled → label strikethrough (`textDecorationLine` via style),
//   - default  → label `text-04`.
//
// The generic per-tool glyph uses `SlidersIcon` (the actions glyph): mobile has
// no per-tool icon set, so a single sensible generic is used for every row.
// Dynamic label/icon colours go through `Text color` / `useToken` (never a
// `text-*` className), per the codebase convention.
// ---------------------------------------------------------------------------

interface ActionLineItemProps {
  /** The tool this row represents. */
  tool: ToolSnapshot;
  /** Whether the tool is forced for the next message. */
  isForced: boolean;
  /** Whether the tool is disabled (enable/disable preference). */
  isDisabled: boolean;
  /** Toggle the tool's enabled/disabled preference (the right-side switch). */
  onToggleEnabled: () => void;
  /** Toggle forcing the tool (tapping the row body). */
  onToggleForced: () => void;
  /** Whether this row is the internal search tool. */
  isSearchTool: boolean;
  /** Open the sources sub-view (search tool only). */
  onOpenSources?: () => void;
  /** Source counts shown next to the search tool's chevron. */
  sourceCount?: { enabled: number; total: number };
}

export function ActionLineItem({
  tool,
  isForced,
  isDisabled,
  onToggleEnabled,
  onToggleForced,
  isSearchTool,
  onOpenSources,
  sourceCount,
}: ActionLineItemProps) {
  const accent = useToken("action-link-05");
  const mutedColor = useToken("text-03");
  const defaultColor = useToken("text-04");

  const labelColor = isForced ? "action-link-05" : "text-04";
  const iconColor = isForced ? accent : isDisabled ? mutedColor : defaultColor;

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={tool.display_name}
      onPress={() => {
        if (isSearchTool) onOpenSources?.();
        else onToggleForced();
      }}
      className={
        isForced
          ? "flex-row items-center justify-between gap-2 rounded-[8px] bg-action-link-01 px-3 py-2"
          : "flex-row items-center justify-between gap-2 rounded-[8px] px-3 py-2 active:bg-background-tint-02"
      }
    >
      <View className="flex-1 flex-row items-center gap-2">
        <SlidersIcon size={16} color={iconColor} />
        <Text
          font="main-ui-body"
          color={labelColor}
          numberOfLines={1}
          style={[
            { flex: 1 },
            isDisabled ? { textDecorationLine: "line-through" } : null,
          ]}
        >
          {tool.display_name}
        </Text>
      </View>

      {isSearchTool ? (
        <View className="flex-row items-center gap-1">
          {sourceCount ? (
            <Text font="secondary-body" color="text-03" numberOfLines={1}>
              {`${sourceCount.enabled} of ${sourceCount.total}`}
            </Text>
          ) : null}
          <ChevronRightIcon size={16} color={mutedColor} />
        </View>
      ) : (
        <Switch
          value={!isDisabled}
          onValueChange={onToggleEnabled}
          accessibilityLabel={`${isDisabled ? "Enable" : "Disable"} ${tool.display_name}`}
        />
      )}
    </Pressable>
  );
}

export default ActionLineItem;
