// StoppedHeader.tsx — "Interrupted Thinking" + step count. Native mirror of web StoppedHeader.

import { memo } from "react";
import { View, Pressable } from "react-native";

import { Text } from "@/components/opal";
import { timelineTokens as T } from "@/theme/timelineTokens";
import { HeaderToggle } from "@/components/message/timeline/headers/HeaderToggle";

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

  return (
    <Pressable
      onPress={isInteractive ? onToggle : undefined}
      disabled={!isInteractive}
      style={{
        flex: 1,
        flexDirection: "row",
        alignItems: "center",
        justifyContent: "space-between",
      }}
    >
      <View
        style={{
          paddingHorizontal: T.headerTextPaddingX,
          paddingVertical: T.headerTextPaddingY,
        }}
      >
        <Text font="main-ui-action" color="text-03">
          Interrupted Thinking
        </Text>
      </View>

      {isInteractive && (
        <HeaderToggle
          isExpanded={isExpanded}
          onToggle={onToggle}
          label={`${totalSteps} ${totalSteps === 1 ? "step" : "steps"}`}
        />
      )}
    </Pressable>
  );
});

export default StoppedHeader;
