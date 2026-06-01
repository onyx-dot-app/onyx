// StreamingHeader.tsx — shimmer activity label + optional elapsed/fold control.
// Native mirror of web StreamingHeader.

import { memo } from "react";
import { View } from "react-native";

import { useStreamingDuration } from "@/state/timeline/hooks/useStreamingDuration";
import { formatDurationSeconds } from "@/lib/formatDuration";
import { timelineTokens as T } from "@/theme/timelineTokens";
import { ShimmerText } from "@/components/message/timeline/primitives/ShimmerText";
import { HeaderToggle } from "@/components/message/timeline/headers/HeaderToggle";

export interface StreamingHeaderProps {
  headerText: string;
  collapsible: boolean;
  isExpanded: boolean;
  onToggle: () => void;
  streamingStartTime?: number;
  toolProcessingDuration?: number;
}

export const StreamingHeader = memo(function StreamingHeader({
  headerText,
  collapsible,
  isExpanded,
  onToggle,
  streamingStartTime,
  toolProcessingDuration,
}: StreamingHeaderProps) {
  const elapsedSeconds = useStreamingDuration(
    toolProcessingDuration === undefined && !!streamingStartTime,
    streamingStartTime,
    toolProcessingDuration
  );
  const showElapsedTime = isExpanded && !!streamingStartTime && elapsedSeconds > 0;

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
          flex: 1,
          minWidth: 0,
          paddingHorizontal: T.headerTextPaddingX,
          paddingVertical: T.headerTextPaddingY,
        }}
      >
        <ShimmerText>{headerText}</ShimmerText>
      </View>

      {collapsible && (
        <HeaderToggle
          isExpanded={isExpanded}
          onToggle={onToggle}
          label={showElapsedTime ? formatDurationSeconds(elapsedSeconds) : undefined}
        />
      )}
    </View>
  );
});

export default StreamingHeader;
