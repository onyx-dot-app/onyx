"use client";

import React, { useCallback } from "react";
import { StopReason } from "@/app/app/services/streamingModels";
import {
  FullChatState,
  RenderType,
} from "@/app/app/message/messageComponents/types";
import { TransformedStep } from "./transformers";
import {
  TimelineRendererComponent,
  TimelineRendererOutput,
} from "./TimelineRendererComponent";
import { TimelineSurface } from "@/lib/timeline/components/primitives/TimelineSurface";

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
      <TimelineSurface className="ps-6 pe-2 pb-2" roundedBottom>
        <TimelineRendererComponent
          key={`${step.key}-compact`}
          packets={step.packets}
          nestedCalls={step.nestedCalls}
          streamPackets={step.streamPackets}
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
    );
  }
);

export default CollapsedStreamingContent;
