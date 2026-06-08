// Native mirror of web MemoryToolRenderer (shares its reducer via memoryStateUtils).
// Web has no MemoriesModal here; the text renders through ExpandableTextDisplay,
// whose maximize control opens the full text in a bottom sheet.

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

  // Fire onComplete on finish (mobile contract; web omits this).
  useFireOnComplete(isComplete, onComplete);

  const renderMemoryText = useCallback(
    (text: string) => (
      <Text font="main-ui-body" color="text-02">
        {text}
      </Text>
    ),
    []
  );

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
