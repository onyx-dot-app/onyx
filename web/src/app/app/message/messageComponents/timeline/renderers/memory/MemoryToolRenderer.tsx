"use client";

import { MemoryToolPacket } from "@/app/app/services/streamingModels";
import {
  MessageRenderer,
  RenderType,
} from "@/app/app/message/messageComponents/interfaces";
import { BlinkingBar } from "@/app/app/message/BlinkingBar";
import { constructCurrentMemoryState } from "./memoryStateUtils";
import Text from "@/refresh-components/texts/Text";
import { SvgEditBig, SvgMaximize2 } from "@opal/icons";
import { cn } from "@/lib/utils";
import { Button } from "@opal/components";
import MemoriesModal from "@/refresh-components/modals/MemoriesModal";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";

/**
 * MemoryToolRenderer - Renders memory tool execution steps
 *
 * States:
 * - Loading (start, no delta): "Saving memory..." with BlinkingBar
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
  const {
    hasStarted,
    noAccess,
    memoryText,
    operation,
    isComplete,
    memoryId,
    index,
  } = memoryState;
  const memoriesModal = useCreateModal();
  const isHighlight = renderType === RenderType.HIGHLIGHT;

  if (!hasStarted) {
    return children([
      {
        icon: SvgEditBig,
        status: "Memory",
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
      <memoriesModal.Provider>
        <MemoriesModal
          initialTargetMemoryId={memoryId}
          initialTargetIndex={index}
          highlightFirstOnOpen
        />
      </memoriesModal.Provider>
      {memoryText ? (
        <div className={cn("w-full flex")}>
          <div className="flex-1 min-w-0">
            <Text as="p" text02 className="text-sm break-words">
              {memoryText}
            </Text>
          </div>
          {/* Expand button */}
          <div className="flex justify-end items-end mt-1 w-8">
            <Button
              prominence="tertiary"
              size="md"
              icon={SvgMaximize2}
              tooltip="View Memories"
              onClick={(e) => {
                e.stopPropagation();
                memoriesModal.toggle(true);
              }}
            />
          </div>
        </div>
      ) : (
        !stopPacketSeen && <BlinkingBar />
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
