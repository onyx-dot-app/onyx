"use client";

import React, { FunctionComponent, useCallback, useMemo } from "react";
import type { IconProps } from "@opal/types";
import { StopReason } from "@/app/app/services/streamingModels";
import { FullChatState } from "@/app/app/message/messageComponents/types";
import type { TransformedStep } from "@/lib/timeline/chat/transformers";
import {
  TimelineRendererComponent,
  TimelineRendererOutput,
  TimelineRendererResult,
} from "@/lib/timeline/chat/TimelineRendererComponent";
import { TimelineStepComposer } from "@/lib/timeline/chat/TimelineStepComposer";
import {
  isPythonToolPackets,
  isSearchToolPackets,
} from "@/lib/timeline/chat/packetHelpers";
import type {
  TimelineEntryStatus,
  TimelineStepPosition,
} from "@/lib/timeline/types";

export interface ChatStepProps {
  step: TransformedStep;
  status: TimelineEntryStatus;
  position: TimelineStepPosition;
  chatState: FullChatState;
  stopPacketSeen: boolean;
  stopReason?: StopReason;
  /** Start open: the run is live, or it is a single non-Python step. */
  defaultExpanded: boolean;
}

/**
 * One chat step on the shared run card: its tool's renderer draws the body,
 * and `RunStep` (through the composer) draws the header and status.
 */
export const ChatStep = React.memo(function ChatStep({
  step,
  status,
  position,
  chatState,
  stopPacketSeen,
  stopReason,
  defaultExpanded,
}: ChatStepProps) {
  const isSearchTool = useMemo(
    () => isSearchToolPackets(step.packets),
    [step.packets]
  );
  const getCollapsedIcon = useCallback(
    (result: TimelineRendererResult) =>
      isSearchTool ? (result.icon as FunctionComponent<IconProps>) : undefined,
    [isSearchTool]
  );

  const renderStep = useCallback(
    (results: TimelineRendererOutput) => (
      <TimelineStepComposer
        results={results}
        isLastStep={position.isLast}
        isFirstStep={position.isFirst}
        collapsible
        getCollapsedIcon={getCollapsedIcon}
        status={status}
      />
    ),
    [position.isFirst, position.isLast, getCollapsedIcon, status]
  );

  return (
    <TimelineRendererComponent
      packets={step.packets}
      nestedCalls={step.nestedCalls}
      streamPackets={step.streamPackets}
      chatState={chatState}
      animate={!stopPacketSeen}
      stopPacketSeen={stopPacketSeen}
      stopReason={stopReason}
      defaultExpanded={defaultExpanded}
      isLastStep={position.isLast}
    >
      {renderStep}
    </TimelineRendererComponent>
  );
});

/** Whether a step starts open in a run of `count` steps. */
export function chatStepStartsOpen(
  step: TransformedStep,
  count: number,
  isLive: boolean
): boolean {
  return isLive || (count === 1 && !isPythonToolPackets(step.packets));
}

export default ChatStep;
