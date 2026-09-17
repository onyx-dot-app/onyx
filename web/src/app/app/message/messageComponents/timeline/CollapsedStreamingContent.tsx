"use client";

import React, { useCallback } from "react";
import { StopReason } from "@/app/app/services/streamingModels";
import {
  FullChatState,
  RenderType,
} from "@/app/app/message/messageComponents/interfaces";
import { TransformedStep } from "@/app/app/message/messageComponents/timeline/transformers";
import {
  TimelineRendererComponent,
  TimelineRendererOutput,
} from "@/app/app/message/messageComponents/timeline/TimelineRendererComponent";
import { TimelineRow } from "@/app/app/message/messageComponents/timeline/primitives/TimelineRow";
import { TimelineSurface } from "@/app/app/message/messageComponents/timeline/primitives/TimelineSurface";

export interface CollapsedStreamingContentProps {
  step: TransformedStep;
  chatState: FullChatState;
  stopReason?: StopReason;
  renderTypeOverride?: RenderType;
}

export const CollapsedStreamingContent = React.memo(
  function CollapsedStreamingContent({
    step,
    chatState,
    stopReason,
    renderTypeOverride,
  }: CollapsedStreamingContentProps) {
    const renderContentOnly = useCallback(
      (results: TimelineRendererOutput) => (
        <>
          {results.map((result, index) => (
            <React.Fragment key={index}>{result.content}</React.Fragment>
          ))}
        </>
      ),
      []
    );

    return (
      <TimelineRow railVariant="spacer">
        <TimelineSurface className="px-2 pb-2" roundedBottom>
          <TimelineRendererComponent
            key={`${step.key}-compact`}
            items={step.items}
            chatState={chatState}
            animate={true}
            stopPacketSeen={false}
            stopReason={stopReason}
            defaultExpanded={false}
            renderTypeOverride={renderTypeOverride}
            isLastStep={true}
          >
            {renderContentOnly}
          </TimelineRendererComponent>
        </TimelineSurface>
      </TimelineRow>
    );
  }
);

export default CollapsedStreamingContent;
