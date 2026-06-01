import { createElement } from "react";
import { Pressable, View } from "react-native";

import { Text } from "@/components/opal";
import { SvgChevronRight } from "@/components/icons/SvgChevronRight";
import { getIconForAction } from "@/lib/actionIcons";
import { useToken } from "@/theme/ThemeProvider";
import type { ToolSnapshot } from "@/lib/types/tools";

// ---------------------------------------------------------------------------
// ActionLineItem — a single tool row in the actions popover (web parity).
//
// Behaviour (mirrors web `ActionLineItem` availability model):
//   - Tapping an AVAILABLE non-search row FORCES the tool (`onToggleForced`).
//     A forced tool is indicated by the row highlight only — there is NO
//     per-tool enable/disable switch (that lives only in the sources sub-view).
//   - An UNAVAILABLE tool is greyed and not pressable.
//   - The search tool is NEVER unavailable; tapping it opens the sources
//     sub-view (`onOpenSources`) and the right side shows a "<enabled> of
//     <total>" count + chevron affordance.
//
// Visual states:
//   - forced       → label `action-link-05` + row `bg-action-link-01` (fixed bg
//                    → static class, toggled conditionally),
//   - unavailable  → muted label/icon (`text-03`), no `active:` affordance,
//   - default      → label `text-04`.
//
// The per-tool glyph comes from `getIconForAction(tool)` — a 1:1 port of web's
// actionUtils mapping (Search→search, WebSearch→globe, ImageGen→image,
// KnowledgeGraph→server, OpenURL→external-link, CodeInterpreter→terminal,
// CodingAgent/default→cpu). Dynamic label/icon colours go through `Text color` /
// `useToken` (never a `text-*` className), per the codebase convention.
// ---------------------------------------------------------------------------

interface ActionLineItemProps {
  /** The tool this row represents. */
  tool: ToolSnapshot;
  /** Whether the tool is forced for the next message. */
  isForced: boolean;
  /** Whether the tool is unavailable (not in the global registry; greyed). */
  isUnavailable: boolean;
  /** Force the tool (tapping the row body) — non-search tools only. */
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
        {/* createElement (not <ToolIcon/>) so the linter doesn't read the
            tool-chosen icon as a component declared during render. */}
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
