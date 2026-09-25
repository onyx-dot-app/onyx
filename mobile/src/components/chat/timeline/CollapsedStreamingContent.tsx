// Live preview of the running step while collapsed. The rail is a spacer, not a rail: the preview
// aligns under the header but must not draw a connector, since it isn't a step in the list.
import { Fragment, memo, useCallback } from "react";

import type { TransformedStep } from "@/chat/timeline/transformers";
import type { StopReason } from "@/chat/streamingModels";
import {
  RenderType,
  type FullChatState,
  type TimelineRendererResult,
} from "@/components/chat/renderers/timelineContract";

import { TimelineRendererComponent } from "./TimelineRendererComponent";
import { TimelineRow } from "./primitives/TimelineRow";
import { TimelineSurface } from "./primitives/TimelineSurface";

export interface CollapsedStreamingContentProps {
  step: TransformedStep;
  chatState: FullChatState;
  stopReason?: StopReason;
  renderTypeOverride?: RenderType;
}

export const CollapsedStreamingContent = memo(
  function CollapsedStreamingContent({
    step,
    chatState,
    stopReason,
    renderTypeOverride,
  }: CollapsedStreamingContentProps) {
    const renderContentOnly = useCallback(
      (results: TimelineRendererResult[]) => (
        <>
          {results.map((result, index) => (
            <Fragment key={index}>{result.content}</Fragment>
          ))}
        </>
      ),
      [],
    );

    return (
      <TimelineRow railVariant="spacer">
        <TimelineSurface className="px-8 pb-8" roundedBottom>
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
  },
);

export default CollapsedStreamingContent;
