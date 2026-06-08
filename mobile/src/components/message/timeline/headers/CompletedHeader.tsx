// Native mirror of web CompletedHeader (MemoriesModal/tooltip -> a memory chip).

import { memo } from "react";
import { View, Pressable } from "react-native";

import { Text } from "@/components/opal";
import { useThemeColors } from "@/theme/ThemeProvider";
import { radii } from "@/theme/generated/radii";
import { SvgEditBig } from "@/components/icons";
import { formatDurationSeconds } from "@/lib/formatDuration";
import { timelineTokens as T } from "@/theme/timelineTokens";
import { HeaderToggle } from "@/components/message/timeline/headers/HeaderToggle";

export interface CompletedHeaderProps {
  totalSteps: number;
  collapsible: boolean;
  isExpanded: boolean;
  onToggle: () => void;
  processingDurationSeconds?: number;
  generatedImageCount?: number;
  isMemoryOnly?: boolean;
  memoryText?: string | null;
  memoryOperation?: "add" | "update" | null;
}

function MemoryChip({
  operation,
}: {
  operation: "add" | "update" | null;
}) {
  const colors = useThemeColors();
  const label = operation === "add" ? "Added to memories" : "Updated memory";
  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        gap: 4,
        backgroundColor: colors["background-tint-02"],
        borderRadius: radii["08"],
        paddingHorizontal: 8,
        paddingVertical: 4,
      }}
    >
      <SvgEditBig size={14} color="text-03" />
      <Text font="secondary-body" color="text-03">
        {label}
      </Text>
    </View>
  );
}

export const CompletedHeader = memo(function CompletedHeader({
  totalSteps,
  collapsible,
  isExpanded,
  onToggle,
  processingDurationSeconds = 0,
  generatedImageCount = 0,
  isMemoryOnly = false,
  memoryText = null,
  memoryOperation = null,
}: CompletedHeaderProps) {
  if (isMemoryOnly) {
    return (
      <View
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
          <MemoryChip operation={memoryOperation} />
        </View>
        {collapsible && totalSteps > 0 && isExpanded && (
          <HeaderToggle
            isExpanded={isExpanded}
            onToggle={onToggle}
            label={`${totalSteps} ${totalSteps === 1 ? "step" : "steps"}`}
          />
        )}
      </View>
    );
  }

  const durationText = processingDurationSeconds
    ? `Thought for ${formatDurationSeconds(processingDurationSeconds)}`
    : "Thought for some time";
  const imageText =
    generatedImageCount > 0
      ? `Generated ${generatedImageCount} ${
          generatedImageCount === 1 ? "image" : "images"
        }`
      : null;

  return (
    <Pressable
      onPress={onToggle}
      style={{
        flex: 1,
        flexDirection: "row",
        alignItems: "center",
        justifyContent: "space-between",
      }}
    >
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: 8,
          paddingHorizontal: T.headerTextPaddingX,
          paddingVertical: T.headerTextPaddingY,
        }}
      >
        <Text font="main-ui-action" color="text-03">
          {isExpanded ? durationText : imageText ?? durationText}
        </Text>
        {memoryOperation && !isExpanded && (
          <MemoryChip operation={memoryOperation} />
        )}
      </View>

      {collapsible && totalSteps > 0 && (
        <HeaderToggle
          isExpanded={isExpanded}
          onToggle={onToggle}
          label={`${totalSteps} ${totalSteps === 1 ? "step" : "steps"}`}
        />
      )}
    </Pressable>
  );
});

export default CompletedHeader;
