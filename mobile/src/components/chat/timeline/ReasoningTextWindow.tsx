// Mobile's port of web's ExpandableTextDisplay — the collapsed half. The expanded reader is
// ReasoningTextSheet, which the message row owns (see `onExpand`).
//
// Must be a ScrollView, not a clipping View: the markdown is a native measure leaf and both
// platforms clamp its height to Yoga's AtMost constraint (iOS `ENRMClampMeasuredSize`, Android
// `MeasurementStore` AT_MOST), so it never overflows and no `justifyContent` trick shifts it.
// A ScrollView measures its content unbounded, which is what makes following the stream possible.
import { useCallback, useRef, useState } from "react";
import { ScrollView, View } from "react-native";

import { StreamingMarkdown } from "@/components/chat/StreamingMarkdown";
import { Button } from "@/components/ui/button";
import SvgExpand from "@/icons/expand";

// Web's box is maxLines × 1.5rem even though its muted body renders at 20px — so 192 matches web's
// box, not 8 lines of mobile text.
const MAX_LINES = 8;
const LINE_HEIGHT = 24;
export const REASONING_WINDOW_MAX_HEIGHT = MAX_LINES * LINE_HEIGHT;

export interface ReasoningTextWindowProps {
  // Heading lifted out (it became the step title) — the window shows only this.
  displayContent: string;
  isStreaming: boolean;
  // Opens the full-text reader, which the message row owns and keeps live. The window deliberately
  // never handles the full text itself.
  onExpand?: () => void;
}

export function ReasoningTextWindow({
  displayContent,
  isStreaming,
  onExpand,
}: ReasoningTextWindowProps) {
  const scrollRef = useRef<ScrollView>(null);
  const [overflows, setOverflows] = useState(false);

  // Only take the gesture when there is genuinely something to scroll. An enabled ScrollView whose
  // content fits still wins the pan on iOS (RN defaults alwaysBounceVertical to true), so a short
  // finished step would become a band where the conversation refuses to scroll.
  const canScroll = overflows && !isStreaming;

  const handleContentSizeChange = useCallback(
    (_width: number, height: number) => {
      setOverflows(height > REASONING_WINDOW_MAX_HEIGHT);
      if (isStreaming) {
        scrollRef.current?.scrollToEnd({ animated: false });
      }
    },
    [isStreaming],
  );

  return (
    <View>
      <ScrollView
        ref={scrollRef}
        style={{ maxHeight: REASONING_WINDOW_MAX_HEIGHT }}
        onContentSizeChange={handleContentSizeChange}
        // While streaming the window follows the newest lines, so a user pan would fight it.
        scrollEnabled={canScroll}
        // Belt and braces with canScroll: stops iOS rubber-banding a window whose content fits.
        alwaysBounceVertical={false}
        // Android needs this for a ScrollView nested in the chat list to receive pans at all.
        nestedScrollEnabled
        showsVerticalScrollIndicator={canScroll}
      >
        <StreamingMarkdown
          content={displayContent}
          isStreaming={isStreaming}
          variant="muted"
        />
      </ScrollView>

      {overflows && onExpand ? (
        <View className="mt-4 flex-row justify-end">
          <Button
            prominence="tertiary"
            size="sm"
            rightIcon={SvgExpand}
            onPress={onExpand}
          >
            View full text
          </Button>
        </View>
      ) : null}
    </View>
  );
}

export default ReasoningTextWindow;
