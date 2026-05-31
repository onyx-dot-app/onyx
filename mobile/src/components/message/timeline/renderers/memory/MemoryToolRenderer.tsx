// MemoryToolRenderer.tsx — renders memory tool execution steps.
//
// Ported from web:
//   web/src/app/app/message/messageComponents/timeline/renderers/memory/MemoryToolRenderer.tsx
// State reducer is shared with web's logic via "@/state/timeline/memoryStateUtils".
//
// States:
//   - Pre-start: icon "edit-big", status "Memory", empty body.
//   - No access: "Memory tool disabled" (text-03). HIGHLIGHT embeds a muted header.
//   - Streaming / delta: status "Updating memory" + the memory text. While the text
//     has not arrived yet (and stop not seen) a BlinkingBar is shown.
//
// DEVIATIONS from web:
//   - Web wraps the memory text in a flex row alongside a tertiary maximize Button
//     that opens a MemoriesModal. Mobile has no MemoriesModal; instead the memory
//     text is rendered through ExpandableTextDisplay (title "Memory"), which renders
//     its own maximize Pressable (SvgMaximize2 size 16, color text-03) opening the
//     full text in a bottom sheet. This matches "tapping maximize shows it full".
//   - Web does not call onComplete (not in its props). The mobile renderer contract
//     requires firing onComplete once the tool is complete, so a ref-guarded effect
//     fires it when memoryState.isComplete becomes true.

import { useCallback, useEffect, useRef } from "react";
import { View } from "react-native";

import type { MemoryToolPacket } from "@/lib/types";
import {
  RenderType,
  type MessageRendererProps,
} from "@/components/message/interfaces";
import { Text } from "@/components/opal";
import { BlinkingBar } from "@/components/message/BlinkingBar";
import { ExpandableTextDisplay } from "@/components/message/ExpandableTextDisplay";
import {
  constructCurrentMemoryState,
  type MemoryState,
} from "@/state/timeline/memoryStateUtils";

const STATUS_LABEL = "Updating memory";

export function MemoryToolRenderer({
  packets,
  stopPacketSeen,
  renderType,
  onComplete,
  children,
}: MessageRendererProps<MemoryToolPacket>) {
  const memoryState: MemoryState = constructCurrentMemoryState(packets);
  const { hasStarted, noAccess, memoryText, isComplete } = memoryState;
  const isHighlight = renderType === RenderType.HIGHLIGHT;

  // Fire onComplete once when the tool finishes (mobile contract; web omits this).
  const completedRef = useRef(false);
  useEffect(() => {
    if (isComplete && !completedRef.current) {
      completedRef.current = true;
      onComplete();
    }
  }, [isComplete, onComplete]);

  const renderMemoryText = useCallback(
    (text: string) => (
      <Text font="main-ui-body" color="text-02">
        {text}
      </Text>
    ),
    []
  );

  // Pre-start: a bare "Memory" step with an empty body.
  if (!hasStarted) {
    return children([
      {
        icon: "edit-big",
        status: "Memory",
        content: <View />,
        supportsCollapsible: false,
        timelineLayout: "timeline",
        noPaddingRight: true,
      },
    ]);
  }

  // No access case.
  if (noAccess) {
    const content = (
      <Text font="main-ui-body" color="text-03">
        Memory tool disabled
      </Text>
    );

    if (isHighlight) {
      return children([
        {
          icon: null,
          status: null,
          supportsCollapsible: false,
          timelineLayout: "content",
          content: (
            <View style={{ flexDirection: "column" }}>
              <Text
                font="main-ui-body"
                color="text-02"
                style={{ marginBottom: 4 }}
              >
                Memory
              </Text>
              {content}
            </View>
          ),
        },
      ]);
    }

    return children([
      {
        icon: "edit-big",
        status: "Memory",
        supportsCollapsible: false,
        timelineLayout: "timeline",
        noPaddingRight: true,
        content,
      },
    ]);
  }

  // Streaming / complete: show the memory text (or a BlinkingBar while it loads).
  const memoryContent = (
    <View style={{ flexDirection: "column" }}>
      {memoryText ? (
        <ExpandableTextDisplay
          title="Memory"
          content={memoryText}
          renderContent={renderMemoryText}
        />
      ) : (
        !stopPacketSeen && <BlinkingBar addMargin />
      )}
    </View>
  );

  if (isHighlight) {
    return children([
      {
        icon: null,
        status: null,
        supportsCollapsible: false,
        timelineLayout: "content",
        content: (
          <View style={{ flexDirection: "column" }}>
            <Text
              font="main-ui-body"
              color="text-02"
              style={{ marginBottom: 4 }}
            >
              {STATUS_LABEL}
            </Text>
            {memoryContent}
          </View>
        ),
      },
    ]);
  }

  return children([
    {
      icon: "edit-big",
      status: STATUS_LABEL,
      supportsCollapsible: false,
      timelineLayout: "timeline",
      noPaddingRight: true,
      content: memoryContent,
    },
  ]);
}

export default MemoryToolRenderer;
