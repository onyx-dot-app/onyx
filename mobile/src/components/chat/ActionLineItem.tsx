import { View } from "react-native";

import { Button } from "@/components/ui/button";
import { LineItemButton } from "@/components/ui/line-item-button";
import { Text } from "@/components/ui/text";
import { getIconForToolId, type ToolSnapshot } from "@/chat/tools";
import SvgChevronRight from "@/icons/chevron-right";
import SvgSlash from "@/icons/slash";

interface ActionLineItemProps {
  tool: ToolSnapshot;
  isForced: boolean;
  // Switched off in this user's agent preferences, not unavailable: the row stays tappable.
  isDisabled: boolean;
  // Assigned to the agent, but its backend integration isn't configured right now — the row is
  // inert (no toggle) unless it's already forced, which stays tappable so it can be un-forced.
  isUnavailable: boolean;
  // Non-null on the row that owns the source sub-view (internal search).
  sourceCounts: { enabled: number; total: number } | null;
  onForceToggle: () => void;
  onToggleEnabled: () => void;
  onOpenSources: () => void;
  onClose: () => void;
}

export function ActionLineItem({
  tool,
  isForced,
  isDisabled,
  isUnavailable,
  sourceCounts,
  onForceToggle,
  onToggleEnabled,
  onOpenSources,
  onClose,
}: ActionLineItemProps) {
  const hasSources = sourceCounts !== null;
  const blocked = isUnavailable && !isForced;

  function handlePress() {
    if (isUnavailable) {
      onForceToggle();
      onClose();
      return;
    }
    if (isDisabled) onToggleEnabled();
    onForceToggle();
    // Forcing search is when its sources matter, so drill in instead of dismissing.
    if (hasSources && !isForced) onOpenSources();
    else onClose();
  }

  const showCount =
    sourceCounts !== null &&
    isForced &&
    sourceCounts.enabled > 0 &&
    sourceCounts.enabled < sourceCounts.total;

  return (
    <LineItemButton
      icon={getIconForToolId(tool.in_code_tool_id)}
      title={tool.display_name || tool.name}
      titleMaxLines={1}
      description={
        isUnavailable ? "Ask an admin to configure this." : undefined
      }
      sizePreset="main-ui"
      variant="section"
      disabled={blocked}
      /*
       * Not LineItemButton's `selected`: its tint is the sheet surface's own token, so a forced
       * row would look identical to an unforced one.
       */
      className={isForced ? "bg-background-tint-02" : undefined}
      // Mobile Text has no strikethrough (web's off-state), so an off/unavailable tool reads muted.
      color={isDisabled || (isUnavailable && !isForced) ? "muted" : "default"}
      onPress={handlePress}
      rightChildren={
        <View className="flex-row items-center gap-2">
          {showCount ? (
            <Text font="secondary-body" color="text-03">
              {`${sourceCounts.enabled} of ${sourceCounts.total}`}
            </Text>
          ) : null}

          {/* Shown whenever the tool is usable — touch has no hover to reveal it on like web
              does, so it can't be hidden until tapped. Hidden when unavailable: there's nothing
              to enable until it's configured. */}
          {!isUnavailable ? (
            <Button
              icon={SvgSlash}
              prominence="tertiary"
              size="sm"
              accessibilityLabel={isDisabled ? "Enable" : "Disable"}
              onPress={onToggleEnabled}
            />
          ) : null}

          {hasSources ? (
            <Button
              icon={SvgChevronRight}
              prominence="tertiary"
              size="sm"
              accessibilityLabel="Configure Sources"
              onPress={onOpenSources}
            />
          ) : null}
        </View>
      }
    />
  );
}
