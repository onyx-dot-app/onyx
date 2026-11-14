import { memo } from "react";
import { View } from "react-native";

import { ShimmerText } from "@/components/chat/timeline/ShimmerText";
import { timelineTokens } from "@/components/chat/timeline/primitives/timelineTokens";
import { Button } from "@/components/ui/button";
import { useStreamingDuration } from "@/hooks/timeline/useStreamingDuration";
import SvgExpand from "@/icons/expand";
import SvgFold from "@/icons/fold";
import { formatDurationSeconds } from "@/lib/time";

export interface StreamingHeaderProps {
  headerText: string;
  collapsible: boolean;
  buttonTitle?: string;
  isExpanded: boolean;
  onToggle: () => void;
  streamingStartTime?: number;
  // Backend `pre_answer_processing_seconds`; freezes the timer once it arrives.
  toolProcessingDuration?: number;
}

export const StreamingHeader = memo(function StreamingHeader({
  headerText,
  collapsible,
  buttonTitle,
  isExpanded,
  onToggle,
  streamingStartTime,
  toolProcessingDuration,
}: StreamingHeaderProps) {
  const elapsedSeconds = useStreamingDuration(
    toolProcessingDuration === undefined,
    streamingStartTime,
    toolProcessingDuration,
  );
  const showElapsedTime =
    isExpanded && streamingStartTime !== undefined && elapsedSeconds > 0;
  const toggleIcon = isExpanded ? SvgFold : SvgExpand;

  return (
    <>
      <View
        style={{
          paddingHorizontal: timelineTokens.headerTextPaddingX,
          paddingVertical: timelineTokens.headerTextPaddingY,
        }}
      >
        <ShimmerText>{headerText}</ShimmerText>
      </View>

      {collapsible ? (
        buttonTitle ? (
          <Button
            prominence="tertiary"
            size="md"
            onPress={onToggle}
            rightIcon={toggleIcon}
          >
            {buttonTitle}
          </Button>
        ) : showElapsedTime ? (
          <Button
            prominence="tertiary"
            size="md"
            onPress={onToggle}
            rightIcon={SvgFold}
          >
            {formatDurationSeconds(elapsedSeconds)}
          </Button>
        ) : (
          <Button
            prominence="tertiary"
            size="md"
            onPress={onToggle}
            icon={toggleIcon}
            accessibilityLabel={
              isExpanded ? "Collapse timeline" : "Expand timeline"
            }
          />
        )
      ) : null}
    </>
  );
});

export default StreamingHeader;
