import React, { useMemo, useCallback } from "react";
import { SvgCircle, SvgCheckCircle, SvgBookOpen } from "@opal/icons";

import {
  PacketType,
  Packet,
  ResearchAgentPacket,
  ResearchAgentStart,
  IntermediateReportDelta,
} from "@/app/app/services/streamingModels";
import {
  MessageRenderer,
  FullChatState,
  RenderType,
} from "@/app/app/message/messageComponents/interfaces";
import { getToolName } from "@/app/app/message/messageComponents/toolDisplayHelpers";
import { StepContainer } from "@/app/app/message/messageComponents/timeline/StepContainer";
import {
  TimelineRendererComponent,
  TimelineRendererOutput,
} from "@/app/app/message/messageComponents/timeline/TimelineRendererComponent";
import { TimelineStepComposer } from "@/app/app/message/messageComponents/timeline/TimelineStepComposer";
import ExpandableTextDisplay from "@/refresh-components/texts/ExpandableTextDisplay";
import Text from "@/refresh-components/texts/Text";
import {
  processContent,
  useMarkdownComponents,
  renderMarkdown,
} from "@/app/app/message/messageComponents/markdownUtils";
import { isReasoningPackets } from "../../packetHelpers";

interface NestedToolGroup {
  sub_turn_index: number;
  toolType: string;
  status: string;
  isComplete: boolean;
  packets: Packet[];
}

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
  state,
  onComplete,
  renderType,
  stopPacketSeen,
  isLastStep = true,
  isHover = false,
  children,
}) => {
  // Extract the research task from the start packet
  const startPacket = packets.find(
    (p) => p.obj.type === PacketType.RESEARCH_AGENT_START
  );
  const researchTask = startPacket
    ? (startPacket.obj as ResearchAgentStart).research_task
    : "";

  // Separate parent packets from nested tool packets
  const { parentPackets, nestedToolGroups } = useMemo(() => {
    const parent: Packet[] = [];
    const nestedBySubTurn = new Map<number, Packet[]>();

    packets.forEach((packet) => {
      const subTurnIndex = packet.placement.sub_turn_index;
      if (subTurnIndex === undefined || subTurnIndex === null) {
        parent.push(packet);
      } else {
        if (!nestedBySubTurn.has(subTurnIndex)) {
          nestedBySubTurn.set(subTurnIndex, []);
        }
        nestedBySubTurn.get(subTurnIndex)!.push(packet);
      }
    });

    // Convert nested packets to groups with metadata
    const groups: NestedToolGroup[] = Array.from(nestedBySubTurn.entries())
      .sort(([a], [b]) => a - b)
      .map(([subTurnIndex, toolPackets]) => {
        const name = getToolName(toolPackets);
        const isComplete = toolPackets.some(
          (p) =>
            p.obj.type === PacketType.SECTION_END ||
            p.obj.type === PacketType.REASONING_DONE
        );
        return {
          sub_turn_index: subTurnIndex,
          toolType: name,
          status: isComplete ? "Complete" : "Running",
          isComplete,
          packets: toolPackets,
        };
      });

    return { parentPackets: parent, nestedToolGroups: groups };
  }, [packets]);

  // Filter nested tool groups based on renderType (COMPACT and HIGHLIGHT show only latest)
  const visibleNestedToolGroups = useMemo(() => {
    if (
      (renderType !== RenderType.COMPACT &&
        renderType !== RenderType.HIGHLIGHT) ||
      nestedToolGroups.length === 0
    ) {
      return nestedToolGroups;
    }
    // COMPACT/HIGHLIGHT mode: show only the latest group (last in sorted array)
    const latestGroup = nestedToolGroups[nestedToolGroups.length - 1];
    return latestGroup ? [latestGroup] : [];
  }, [renderType, nestedToolGroups]);

  // Check completion from parent packets
  const isComplete = parentPackets.some(
    (p) => p.obj.type === PacketType.SECTION_END
  );

  // Determine if report is actively streaming
  const isReportStreaming = !isComplete && !stopPacketSeen;

  // Build report content from parent packets
  const fullReportContent = parentPackets
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
    "text-text-03 font-main-ui-body"
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
            <div className="flex flex-col pl-[var(--timeline-common-text-padding)]">
              <Text as="p" text04 mainUiMuted className="mb-1">
                Research Report
              </Text>
              <ExpandableTextDisplay
                title="Research Report"
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
        return (
          <TimelineRendererComponent
            key={latestGroup.sub_turn_index}
            packets={latestGroup.packets}
            chatState={state}
            animate={!stopPacketSeen && !latestGroup.isComplete}
            stopPacketSeen={stopPacketSeen}
            defaultExpanded={false}
            renderTypeOverride={RenderType.HIGHLIGHT}
            isLastStep={true}
            isHover={isHover}
          >
            {(results: TimelineRendererOutput) =>
              children([
                {
                  icon: null,
                  status: null,
                  content: (
                    <>
                      {results.map((result, index) => (
                        <React.Fragment key={index}>
                          {result.content}
                        </React.Fragment>
                      ))}
                    </>
                  ),
                  supportsCollapsible: true,
                  timelineLayout: "content",
                },
              ])
            }
          </TimelineRendererComponent>
        );
      }
    }

    // Fallback: research task with header embedded
    if (researchTask) {
      return children([
        {
          icon: null,
          status: null,
          content: (
            <div className="flex flex-col pl-[var(--timeline-common-text-padding)]">
              <Text as="p" text04 mainUiMuted>
                Research Task
              </Text>
              <Text as="p" text03 mainUiMuted>
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
          header="Research Task"
          collapsible={true}
          isLastStep={
            !stopPacketSeen &&
            nestedToolGroups.length === 0 &&
            !fullReportContent &&
            !isComplete
          }
          isHover={isHover}
        >
          <div className="pl-[var(--timeline-common-text-padding)]">
            <Text as="p" text02 mainUiMuted>
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

          const isReasoning = isReasoningPackets(group.packets);

          return (
            <TimelineRendererComponent
              key={group.sub_turn_index}
              packets={group.packets}
              chatState={state}
              animate={!stopPacketSeen && !group.isComplete}
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
                  noPaddingRight={isReasoning}
                />
              )}
            </TimelineRendererComponent>
          );
        })}

      {/* Intermediate report - hidden when tools are active in compact mode */}
      {fullReportContent && !showOnlyTools && (
        <StepContainer
          stepIcon={SvgBookOpen}
          header="Research Report"
          isLastStep={!stopPacketSeen && !isComplete}
          isFirstStep={!researchTask && nestedToolGroups.length === 0}
          isHover={isHover}
          noPaddingRight={true}
        >
          <div className="pl-[var(--timeline-common-text-padding)]">
            <ExpandableTextDisplay
              title="Research Report"
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
