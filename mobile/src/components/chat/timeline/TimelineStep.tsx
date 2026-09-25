// Its own module, unlike web (which keeps this private inside ExpandedTimelineContent): mobile's
// ParallelTimelineTabs also needs it, and importing it from there would cycle.
import { memo, useCallback, useMemo } from "react";

import {
  isPythonToolPackets,
  isSearchToolPackets,
} from "@/chat/timeline/packetHelpers";
import type { TransformedStep } from "@/chat/timeline/transformers";
import type {
  FullChatState,
  TimelineRendererResult,
} from "@/components/chat/renderers/timelineContract";
import type { StopReason } from "@/chat/streamingModels";
import type { IconFunctionComponent } from "@/icons/types";

import { TimelineRendererComponent } from "./TimelineRendererComponent";
import { TimelineStepComposer } from "./TimelineStepComposer";

export interface TimelineStepProps {
  step: TransformedStep;
  chatState: FullChatState;
  stopPacketSeen: boolean;
  stopReason?: StopReason;
  isLastStep: boolean;
  isFirstStep: boolean;
  isSingleStep: boolean;
  isStreaming?: boolean;
}

export const TimelineStep = memo(function TimelineStep({
  step,
  chatState,
  stopPacketSeen,
  stopReason,
  isLastStep,
  isFirstStep,
  isSingleStep,
  isStreaming = false,
}: TimelineStepProps) {
  const isSearchTool = useMemo(
    () => isSearchToolPackets(step.packets),
    [step.packets],
  );
  const isPythonTool = useMemo(
    () => isPythonToolPackets(step.packets),
    [step.packets],
  );

  // Collapsed, a search step keeps its own glyph instead of the generic expand chevron.
  const getCollapsedIcon = useCallback(
    (result: TimelineRendererResult): IconFunctionComponent | undefined =>
      isSearchTool ? (result.icon ?? undefined) : undefined,
    [isSearchTool],
  );

  const renderStep = useCallback(
    (results: TimelineRendererResult[]) => (
      <TimelineStepComposer
        results={results}
        isLastStep={isLastStep}
        isFirstStep={isFirstStep}
        isSingleStep={isSingleStep}
        collapsible
        getCollapsedIcon={getCollapsedIcon}
      />
    ),
    [isFirstStep, isLastStep, isSingleStep, getCollapsedIcon],
  );

  return (
    <TimelineRendererComponent
      packets={step.packets}
      chatState={chatState}
      animate={!stopPacketSeen}
      stopPacketSeen={stopPacketSeen}
      stopReason={stopReason}
      defaultExpanded={isStreaming || (isSingleStep && !isPythonTool)}
      isLastStep={isLastStep}
    >
      {renderStep}
    </TimelineRendererComponent>
  );
});

export default TimelineStep;
