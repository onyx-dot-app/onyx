// One tool row in the actions menu. RN port of
// web/src/refresh-components/popovers/ActionsPopover/ActionLineItem.tsx, minus MCP, OAuth, the
// admin cog, source counts and the search drill-in.
import { Button } from "@/components/ui/button";
import { LineItemButton } from "@/components/ui/line-item-button";
import { getIconForToolId, type ToolSnapshot } from "@/chat/tools";
import SvgSlash from "@/icons/slash";

interface ActionLineItemProps {
  tool: ToolSnapshot;
  isForced: boolean;
  // Switched off in this user's agent preferences. The row stays tappable: tapping it re-enables
  // and forces the tool in one gesture, as web does.
  isDisabled: boolean;
  onForceToggle: () => void;
  onToggleEnabled: () => void;
  onClose: () => void;
}

export function ActionLineItem({
  tool,
  isForced,
  isDisabled,
  onForceToggle,
  onToggleEnabled,
  onClose,
}: ActionLineItemProps) {
  function handlePress() {
    if (isDisabled) onToggleEnabled();
    onForceToggle();
    onClose();
  }

  return (
    <LineItemButton
      icon={getIconForToolId(tool.in_code_tool_id)}
      title={tool.display_name || tool.name}
      titleMaxLines={1}
      sizePreset="main-ui"
      variant="section"
      // Not LineItemButton's `selected`: its tint is background-tint-00, the very token the sheet
      // surface uses, so a forced row would look identical to an unforced one.
      className={isForced ? "bg-background-tint-02" : undefined}
      // Web strikes the label through; mobile's Text/Content have no strikethrough, so an off tool
      // reads as muted instead.
      color={isDisabled ? "muted" : "default"}
      onPress={handlePress}
      rightChildren={
        // Web reveals this on row hover; touch has no hover, so it stays visible.
        <Button
          icon={SvgSlash}
          prominence="tertiary"
          size="sm"
          accessibilityLabel={isDisabled ? "Enable" : "Disable"}
          onPress={onToggleEnabled}
        />
      }
    />
  );
}
