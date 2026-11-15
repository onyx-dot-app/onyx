import React, { useMemo, useCallback } from "react";
import { useTranslations } from "next-intl";
import { SvgCircle, SvgCheckCircle, SvgBookOpen } from "@opal/icons";

import {
  PacketType,
  ResearchAgentPacket,
  ResearchAgentStart,
  IntermediateReportDelta,
} from "@/app/app/services/streamingModels";
import {
  MessageRenderer,
  FullChatState,
  RenderType,
} from "@/app/app/message/messageComponents/types";
import { StepContainer } from "@/app/app/message/messageComponents/timeline/StepContainer";
import {
  isGroupEndPacket,
  NestedCall,
} from "@/app/app/message/messageComponents/timeline/packetHelpers";
import {
  TimelineRendererComponent,
  TimelineRendererOutput,
} from "@/app/app/message/messageComponents/timeline/TimelineRendererComponent";
import { TimelineStepComposer } from "@/app/app/message/messageComponents/timeline/TimelineStepComposer";
import ExpandableTextDisplay from "@/refresh-components/texts/ExpandableTextDisplay";
import { Text } from "@opal/components";
import {
  processContent,
  useMarkdownComponents,
  renderMarkdown,
} from "@/app/app/message/messageComponents/markdownUtils";

// A nested call has no nested calls of its own.
const CALLS_OF_A_NESTED_CALL: NestedCall[] = [];

/**
 * ResearchAgentRenderer - Renders research agent steps in deep research
 *
 * Segregates packets by tool and uses StepContainer + TimelineRendererComponent.
 *
 * RenderType modes:
 * - FULL: Shows all nested tool groups, research task, and report. Headers passed as `status` prop.
 *         Used when step is expanded in timeline.
 * - COMPACT: Shows only the latest active item (tool or report). Header passed as `status` prop.
 *            Used when step is collapsed in timeline, still wrapped in StepContainer.
 * - HIGHLIGHT: Shows only the latest active item with header embedded directly in content.
 *              No StepContainer wrapper. Used for parallel streaming preview.
 *              Nested tools are rendered with HIGHLIGHT mode recursively.
 */
export const ResearchAgentRenderer: MessageRenderer<
  ResearchAgentPacket,
  FullChatState
> = ({
  packets,
  nestedCalls,
  state,
  onComplete,
  renderType,
  stopPacketSeen,
  isLastStep = true,
  isHover = false,
  children,
}) => {
  const t = useTranslations("chat.messages.timeline");

  // Extract the research task from the start packet
  const startPacket = packets.find(
    (p) => p.obj.type === PacketType.RESEARCH_AGENT_START
  );
  const researchTask = startPacket
    ? (startPacket.obj as ResearchAgentStart).research_task
    : "";

  // Filter nested tool groups based on renderType (COMPACT and HIGHLIGHT show only latest)
  const visibleNestedToolGroups = useMemo(() => {
    if (
      (renderType !== RenderType.COMPACT &&
        renderType !== RenderType.HIGHLIGHT) ||
      nestedCalls.length === 0
    ) {
      return nestedCalls;
    }
    // COMPACT/HIGHLIGHT mode: show only the latest group (last in sorted array)
    const latestGroup = nestedCalls[nestedCalls.length - 1];
    return latestGroup ? [latestGroup] : [];
  }, [renderType, nestedCalls]);

  const isComplete = packets.some(isGroupEndPacket);

  // Determine if report is actively streaming
  const isReportStreaming = !isComplete && !stopPacketSeen;

  // Build report content from parent packets
  const fullReportContent = packets
    .map((packet) => {
      if (packet.obj.type === PacketType.INTERMEDIATE_REPORT_DELTA) {
        return (packet.obj as IntermediateReportDelta).content;
      }
      return "";
    })
    .join("");

  // Condensed modes: show only the currently active/streaming section
  const isCompact = renderType === RenderType.COMPACT;
  const isHighlight = renderType === RenderType.HIGHLIGHT;
  const isCondensedMode = isCompact || isHighlight;
  // Report takes priority if it has content (means tools are done, report is streaming)
  const showOnlyReport =
    isCondensedMode && fullReportContent && visibleNestedToolGroups.length > 0;
  const showOnlyTools =
    isCondensedMode && !fullReportContent && visibleNestedToolGroups.length > 0;

  // Process content once for consistent markdown handling
  // This ensures code block extraction uses the same offsets as rendered content
  const processedReportContent = useMemo(
    () => processContent(fullReportContent),
    [fullReportContent]
  );

  // Get markdown components for rendering (stable across renders)
  // Uses processed content so code block extraction offsets match rendered content
  const markdownComponents = useMarkdownComponents(
    state,
    processedReportContent,
    "main-ui-body",
    "text-03"
  );

  // Stable callbacks to avoid creating new functions on every render
  // renderReport renders the processed content
  // Uses pre-computed processedReportContent since ExpandableTextDisplay
  // passes the same fullReportContent that we processed above
  // Parameters are required by ExpandableTextDisplay interface but we use
  // the pre-processed content to ensure offsets match code block extraction
  const renderReport = useCallback(
    (_content: string, _isExpanded?: boolean) =>
      renderMarkdown(
        processedReportContent,
        markdownComponents,
        "text-text-03 font-main-ui-body"
      ),
    [processedReportContent, markdownComponents]
  );

  // HIGHLIGHT mode: return raw content with header embedded in content
  if (isHighlight) {
    if (showOnlyReport) {
      return children([
        {
          icon: null,
          status: null,
          content: (
            <div className="flex flex-col ps-(--timeline-common-text-padding)">
              <div className="mb-1">
                <Text as="p" font="main-ui-muted" color="text-04">
                  {t("researchAgent.report.title")}
                </Text>
              </div>
              <ExpandableTextDisplay
                title={t("researchAgent.report.title")}
                content={fullReportContent}
                maxLines={5}
                renderContent={renderReport}
                isStreaming={isReportStreaming}
              />
            </div>
          ),
          supportsCollapsible: true,
          timelineLayout: "content",
        },
      ]);
    }

    if (showOnlyTools) {
      const latestGroup = visibleNestedToolGroups[0];
      if (latestGroup) {
        return children([
          {
            icon: null,
            status: null,
            content: (
              <TimelineRendererComponent
                key={latestGroup.subTurnIndex}
                packets={latestGroup.packets}
                nestedCalls={CALLS_OF_A_NESTED_CALL}
                streamPackets={latestGroup.packets}
                chatState={state}
                animate={!stopPacketSeen && !latestGroup.complete}
                stopPacketSeen={stopPacketSeen}
                defaultExpanded={false}
                renderTypeOverride={RenderType.HIGHLIGHT}
                isLastStep={true}
                isHover={isHover}
              >
                {(results: TimelineRendererOutput) => (
                  <>
                    {results.map((result, index) => (
                      <React.Fragment key={index}>
                        {result.content}
                      </React.Fragment>
                    ))}
                  </>
                )}
              </TimelineRendererComponent>
            ),
            supportsCollapsible: true,
            timelineLayout: "content",
          },
        ]);
      }
    }

    // Fallback: research task with header embedded
    if (researchTask) {
      return children([
        {
          icon: null,
          status: null,
          content: (
            <div className="flex flex-col ps-(--timeline-common-text-padding)">
              <Text as="p" font="main-ui-muted" color="text-04">
                {t("researchAgent.task.title")}
              </Text>
              <Text as="p" font="main-ui-muted" color="text-03">
                {researchTask}
              </Text>
            </div>
          ),
          supportsCollapsible: true,
          timelineLayout: "content",
        },
      ]);
    }

    return children([
      {
        icon: null,
        status: null,
        content: <></>,
        supportsCollapsible: true,
        timelineLayout: "content",
      },
    ]);
  }

  // Build content using StepContainer pattern
  const researchAgentContent = (
    <div className="flex flex-col">
      {/* Research Task - hidden in compact mode when tools/report are active */}
      {researchTask && !showOnlyReport && !showOnlyTools && (
        <StepContainer
          stepIcon={SvgCircle}
          header={t("researchAgent.task.title")}
          collapsible={true}
          isLastStep={
            !stopPacketSeen &&
            nestedCalls.length === 0 &&
            !fullReportContent &&
            !isComplete
          }
          isHover={isHover}
        >
          <div className="ps-(--timeline-common-text-padding)">
            <Text as="p" font="main-ui-muted" color="text-02">
              {researchTask}
            </Text>
          </div>
        </StepContainer>
      )}

      {/* Nested tool calls - hidden when report is streaming in compact mode */}
      {!showOnlyReport &&
        visibleNestedToolGroups.map((group, index) => {
          const isLastNestedStep =
            !stopPacketSeen &&
            index === visibleNestedToolGroups.length - 1 &&
            !fullReportContent &&
            !isComplete;

          return (
            <TimelineRendererComponent
              key={group.subTurnIndex}
              packets={group.packets}
              nestedCalls={CALLS_OF_A_NESTED_CALL}
              streamPackets={group.packets}
              chatState={state}
              animate={!stopPacketSeen && !group.complete}
              stopPacketSeen={stopPacketSeen}
              defaultExpanded={true}
              isLastStep={isLastNestedStep}
              isHover={isHover}
            >
              {(results: TimelineRendererOutput) => (
                <TimelineStepComposer
                  results={results}
                  isLastStep={isLastNestedStep}
                  isFirstStep={!researchTask && index === 0}
                  isSingleStep={false}
                  collapsible={true}
                />
              )}
            </TimelineRendererComponent>
          );
        })}

      {/* Intermediate report - hidden when tools are active in compact mode */}
      {fullReportContent && !showOnlyTools && (
        <StepContainer
          stepIcon={SvgBookOpen}
          header={t("researchAgent.report.title")}
          isLastStep={!stopPacketSeen && !isComplete}
          isFirstStep={!researchTask && nestedCalls.length === 0}
          isHover={isHover}
          noPaddingRight={true}
        >
          <div className="ps-(--timeline-common-text-padding)">
            <ExpandableTextDisplay
              title={t("researchAgent.report.title")}
              content={fullReportContent}
              renderContent={renderReport}
              isStreaming={isReportStreaming}
            />
          </div>
        </StepContainer>
      )}
    </div>
  );

  // Return simplified result (no icon, no status)
  return children([
    {
      icon: null,
      status: null,
      content: researchAgentContent,
      supportsCollapsible: true,
      timelineLayout: "content",
    },
  ]);
};
