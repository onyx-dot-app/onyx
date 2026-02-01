"use client";

import React, { useCallback } from "react";
import { StopReason } from "@/app/app/services/streamingModels";
import { FullChatState, RenderType } from "../interfaces";
import { TransformedStep } from "./transformers";
import { cn } from "@/lib/utils";
import {
  TimelineRendererComponent,
  TimelineRendererOutput,
} from "./TimelineRendererComponent";

// =============================================================================
// TimelineContentRow - Layout helper for content rows
// =============================================================================

interface TimelineContentRowProps {
  className?: string;
  children: React.ReactNode;
}

const TimelineContentRow: React.FC<TimelineContentRowProps> = ({
  className,
  children,
}) => (
  <div className="flex w-full">
    <div className="w-9" />
    <div className={cn("w-full", className)}>{children}</div>
  </div>
);

// =============================================================================
// CollapsedStreamingContent Component
// =============================================================================

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
    const noopComplete = useCallback(() => {}, []);
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
      <TimelineContentRow className="bg-background-tint-00 rounded-b-12 px-2 pb-2">
        <TimelineRendererComponent
          key={`${step.key}-compact`}
          packets={step.packets}
          chatState={chatState}
          onComplete={noopComplete}
          animate={true}
          stopPacketSeen={false}
          stopReason={stopReason}
          defaultExpanded={false}
          renderTypeOverride={renderTypeOverride}
          isLastStep={true}
        >
          {renderContentOnly}
        </TimelineRendererComponent>
      </TimelineContentRow>
    );
  }
);

export default CollapsedStreamingContent;
