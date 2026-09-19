import { memo } from "react";
import { Pressable, View } from "react-native";

import { timelineTokens } from "@/components/chat/timeline/primitives/timelineTokens";
import { Button } from "@/components/ui/button";
import { Text } from "@/components/ui/text";
import SvgExpand from "@/icons/expand";
import SvgFold from "@/icons/fold";

export interface StoppedHeaderProps {
  totalSteps: number;
  collapsible: boolean;
  isExpanded: boolean;
  onToggle: () => void;
}

export const StoppedHeader = memo(function StoppedHeader({
  totalSteps,
  collapsible,
  isExpanded,
  onToggle,
}: StoppedHeaderProps) {
  const isInteractive = collapsible && totalSteps > 0;

  const label = (
    <View
      style={{
        paddingHorizontal: timelineTokens.headerTextPaddingX,
        paddingVertical: timelineTokens.headerTextPaddingY,
      }}
    >
      <Text font="main-ui-action" color="text-03">
        Interrupted Thinking
      </Text>
    </View>
  );

  if (!isInteractive) {
    return (
      <View className="w-full flex-row items-center justify-between">
        {label}
      </View>
    );
  }

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ expanded: isExpanded }}
      onPress={onToggle}
      className="w-full flex-row items-center justify-between rounded-12"
    >
      {label}
      <Button
        prominence="tertiary"
        size="md"
        onPress={onToggle}
        rightIcon={isExpanded ? SvgFold : SvgExpand}
      >
        {`${totalSteps} ${totalSteps === 1 ? "step" : "steps"}`}
      </Button>
    </Pressable>
  );
});

export default StoppedHeader;
