// CollapsedStreamingContent.tsx — collapsed-while-streaming body: a spacer-rail
// row + rounded-bottom surface rendering only the live step's content (no step
// chrome). Native mirror of web CollapsedStreamingContent.

import { Fragment, memo } from "react";

import type { StopReason } from "@/lib/types";
import { RenderType, type FullChatState } from "@/components/message/interfaces";
import type { TransformedStep } from "@/state/timeline/transformers";
import { TimelineRow } from "@/components/message/timeline/primitives/TimelineRow";
import { TimelineSurface } from "@/components/message/timeline/primitives/TimelineSurface";
import {
  TimelineRendererComponent,
  type TimelineRendererOutput,
} from "@/components/message/timeline/TimelineRendererComponent";

export interface CollapsedStreamingContentProps {
  step: TransformedStep;
  chatState: FullChatState;
  stopReason?: StopReason;
  renderTypeOverride?: RenderType;
}

export const CollapsedStreamingContent = memo(function CollapsedStreamingContent({
  step,
  chatState,
  stopReason,
  renderTypeOverride,
}: CollapsedStreamingContentProps) {
  const renderContentOnly = (results: TimelineRendererOutput) => (
    <>
      {results.map((result, index) => (
        <Fragment key={index}>{result.content}</Fragment>
      ))}
    </>
  );

  return (
    <TimelineRow railVariant="spacer">
      <TimelineSurface style={{ paddingHorizontal: 8, paddingBottom: 8 }} roundedBottom>
        <TimelineRendererComponent
          key={`${step.key}-compact`}
          packets={step.packets}
          chatState={chatState}
          animate
          stopPacketSeen={false}
          stopReason={stopReason}
          defaultExpanded={false}
          renderTypeOverride={renderTypeOverride}
          isLastStep
        >
          {renderContentOnly}
        </TimelineRendererComponent>
      </TimelineSurface>
    </TimelineRow>
  );
});

export default CollapsedStreamingContent;
