// MemoryToolRenderer.tsx — renders memory tool execution steps. Native mirror of web MemoryToolRenderer.
// State reducer is shared with web's logic via "@/state/timeline/memoryStateUtils".
//
// DEVIATIONS from web:
//   - Web has no MemoriesModal here; the memory text is rendered through
//     ExpandableTextDisplay, whose maximize control opens the full text in a
//     bottom sheet.
//   - Web does not fire onComplete; the mobile renderer contract requires it, so
//     a ref-guarded effect fires it when memoryState.isComplete becomes true.

import { useCallback } from "react";
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
import { useFireOnComplete } from "@/state/timeline/hooks/useFireOnComplete";

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
  useFireOnComplete(isComplete, onComplete);

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
