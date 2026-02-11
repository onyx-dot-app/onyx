import React from "react";
import { MemoryToolPacket } from "@/app/app/services/streamingModels";
import {
  MessageRenderer,
  RenderType,
} from "@/app/app/message/messageComponents/interfaces";
import { BlinkingDot } from "@/app/app/message/BlinkingDot";
import { constructCurrentMemoryState } from "./memoryStateUtils";
import Text from "@/refresh-components/texts/Text";
import { SvgEditBig } from "@opal/icons";

/**
 * MemoryToolRenderer - Renders memory tool execution steps
 *
 * States:
 * - Loading (start, no delta): "Saving memory..." with BlinkingDot
 * - Delta received: operation label + memory text
 * - Complete (SectionEnd): "Memory saved" / "Memory updated" + memory text
 * - No Access: "Memory tool disabled"
 */
export const MemoryToolRenderer: MessageRenderer<MemoryToolPacket, {}> = ({
  packets,
  stopPacketSeen,
  renderType,
  children,
}) => {
  const memoryState = constructCurrentMemoryState(packets);
  const { hasStarted, noAccess, memoryText, operation, isComplete } =
    memoryState;
  const isHighlight = renderType === RenderType.HIGHLIGHT;

  if (!hasStarted) {
    return children([
      {
        icon: SvgEditBig,
        status: null,
        content: <div />,
        supportsCollapsible: false,
        timelineLayout: "timeline",
      },
    ]);
  }

  // No access case
  if (noAccess) {
    const content = (
      <Text as="p" text03 className="text-sm">
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
            <div className="flex flex-col">
              <Text as="p" text02 className="text-sm mb-1">
                Memory
              </Text>
              {content}
            </div>
          ),
        },
      ]);
    }

    return children([
      {
        icon: SvgEditBig,
        status: "Memory",
        supportsCollapsible: false,
        timelineLayout: "timeline",
        content,
      },
    ]);
  }

  // Determine status text
  let statusLabel = "Updating memory";

  const memoryContent = (
    <div className="flex flex-col">
      {memoryText ? (
        <Text as="p" text03 className="text-sm">
          {memoryText}
        </Text>
      ) : (
        !stopPacketSeen && <BlinkingDot />
      )}
    </div>
  );

  if (isHighlight) {
    return children([
      {
        icon: null,
        status: null,
        supportsCollapsible: false,
        timelineLayout: "content",
        content: (
          <div className="flex flex-col">
            <Text as="p" text02 className="text-sm mb-1">
              {statusLabel}
            </Text>
            {memoryContent}
          </div>
        ),
      },
    ]);
  }

  return children([
    {
      icon: SvgEditBig,
      status: statusLabel,
      supportsCollapsible: false,
      timelineLayout: "timeline",
      content: memoryContent,
    },
  ]);
};
