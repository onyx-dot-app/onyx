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
  sourceCounts,
  onForceToggle,
  onToggleEnabled,
  onOpenSources,
  onClose,
}: ActionLineItemProps) {
  const hasSources = sourceCounts !== null;

  function handlePress() {
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
      sizePreset="main-ui"
      variant="section"
      /*
       * Not LineItemButton's `selected`: its tint is the sheet surface's own token, so a forced
       * row would look identical to an unforced one.
       */
      className={isForced ? "bg-background-tint-02" : undefined}
      // Mobile Text has no strikethrough (web's off-state), so an off tool reads as muted.
      color={isDisabled ? "muted" : "default"}
      onPress={handlePress}
      rightChildren={
        <View className="flex-row items-center gap-2">
          {showCount ? (
            <Text font="secondary-body" color="text-03">
              {`${sourceCounts.enabled} of ${sourceCounts.total}`}
            </Text>
          ) : null}

          {/* Always visible: touch has no hover to reveal it on, as web does. */}
          <Button
            icon={SvgSlash}
            prominence="tertiary"
            size="sm"
            accessibilityLabel={isDisabled ? "Enable" : "Disable"}
            onPress={onToggleEnabled}
          />

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
