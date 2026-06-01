import { createElement } from "react";
import { Pressable, View } from "react-native";

import { Text } from "@/components/opal";
import { SvgChevronRight } from "@/components/icons/SvgChevronRight";
import { getIconForAction } from "@/lib/actionIcons";
import { useToken } from "@/theme/ThemeProvider";
import type { ToolSnapshot } from "@/lib/types/tools";

// A single tool row in the actions popover (web parity). Forced tools are shown
// by row highlight only (no per-tool switch); unavailable tools are greyed/inert;
// the search row opens the sources sub-view instead of forcing.
interface ActionLineItemProps {
  tool: ToolSnapshot;
  isForced: boolean;
  // Not in the global registry; greyed.
  isUnavailable: boolean;
  onToggleForced: () => void;
  isSearchTool: boolean;
  onOpenSources?: () => void;
  sourceCount?: { enabled: number; total: number };
}

export function ActionLineItem({
  tool,
  isForced,
  isUnavailable,
  onToggleForced,
  isSearchTool,
  onOpenSources,
  sourceCount,
}: ActionLineItemProps) {
  const accent = useToken("action-link-05");
  const mutedColor = useToken("text-03");
  const defaultColor = useToken("text-04");

  const labelColor = isForced
    ? "action-link-05"
    : isUnavailable
      ? "text-03"
      : "text-04";
  const iconColor = isForced
    ? accent
    : isUnavailable
      ? mutedColor
      : defaultColor;
  const toolIcon = getIconForAction(tool);

  // Search opens sources; available non-search forces; unavailable is inert.
  function handlePress() {
    if (isSearchTool) onOpenSources?.();
    else onToggleForced();
  }

  const rowClassName = isForced
    ? "flex-row items-center justify-between gap-2 rounded-[8px] bg-action-link-01 px-3 py-2"
    : isUnavailable
      ? "flex-row items-center justify-between gap-2 rounded-[8px] px-3 py-2"
      : "flex-row items-center justify-between gap-2 rounded-[8px] px-3 py-2 active:bg-background-tint-02";

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={tool.display_name}
      accessibilityState={isUnavailable ? { disabled: true } : undefined}
      disabled={!isSearchTool && isUnavailable}
      onPress={handlePress}
      className={rowClassName}
    >
      <View className="flex-1 flex-row items-center gap-2">
        {/* createElement so the linter doesn't read toolIcon as a component
            declared during render. */}
        {createElement(toolIcon, { size: 16, color: iconColor })}
        <Text
          font="main-ui-body"
          color={labelColor}
          numberOfLines={1}
          style={{ flex: 1 }}
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
          <SvgChevronRight size={16} color={mutedColor} />
        </View>
      ) : null}
    </Pressable>
  );
}
