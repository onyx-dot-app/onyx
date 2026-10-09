// Web's memory-only branch (a tag whose tooltip opens MemoriesModal) is dropped: the memory renderer
// is a later phase, and the design drops the tooltip/modal on mobile (§8(g)).
import { memo } from "react";
import { Pressable, View } from "react-native";

import { timelineTokens } from "@/components/chat/timeline/primitives/timelineTokens";
import { Button } from "@/components/ui/button";
import { Text } from "@/components/ui/text";
import SvgExpand from "@/icons/expand";
import SvgFold from "@/icons/fold";
import { formatDurationSeconds } from "@/lib/time";

export interface CompletedHeaderProps {
  totalSteps: number;
  collapsible: boolean;
  isExpanded: boolean;
  onToggle: () => void;
  processingDurationSeconds?: number;
  generatedImageCount?: number;
}

export const CompletedHeader = memo(function CompletedHeader({
  totalSteps,
  collapsible,
  isExpanded,
  onToggle,
  processingDurationSeconds = 0,
  generatedImageCount = 0,
}: CompletedHeaderProps) {
  const durationText = processingDurationSeconds
    ? `Thought for ${formatDurationSeconds(processingDurationSeconds)}`
    : "Thought for some time";

  const imageText =
    generatedImageCount > 0
      ? `Generated ${generatedImageCount} ${
          generatedImageCount === 1 ? "image" : "images"
        }`
      : null;

  const showToggle = collapsible && totalSteps > 0;

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ expanded: isExpanded }}
      onPress={onToggle}
      className="w-full flex-row items-center justify-between"
    >
      <View
        className="flex-row items-center gap-8"
        style={{
          paddingHorizontal: timelineTokens.headerTextPaddingX,
          paddingVertical: timelineTokens.headerTextPaddingY,
        }}
      >
        <Text font="main-ui-action" color="text-03">
          {isExpanded ? durationText : (imageText ?? durationText)}
        </Text>
      </View>

      {showToggle ? (
        <Button
          prominence="tertiary"
          size="md"
          onPress={onToggle}
          rightIcon={isExpanded ? SvgFold : SvgExpand}
        >
          {`${totalSteps} ${totalSteps === 1 ? "step" : "steps"}`}
        </Button>
      ) : null}
    </Pressable>
  );
});

export default CompletedHeader;
