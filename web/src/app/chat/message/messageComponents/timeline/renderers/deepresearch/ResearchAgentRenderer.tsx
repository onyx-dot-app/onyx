import React, {
  useEffect,
  useMemo,
  useRef,
  useCallback,
  FunctionComponent,
} from "react";
import { FiTarget } from "react-icons/fi";
import { SvgCircle, SvgCheckCircle } from "@opal/icons";
import { IconProps } from "@opal/types";

import {
  PacketType,
  Packet,
  ResearchAgentPacket,
  ResearchAgentStart,
  IntermediateReportDelta,
} from "@/app/chat/services/streamingModels";
import {
  MessageRenderer,
  FullChatState,
  RenderType,
} from "@/app/chat/message/messageComponents/interfaces";
import { getToolName } from "@/app/chat/message/messageComponents/toolDisplayHelpers";
import { StepContainer } from "@/app/chat/message/messageComponents/timeline/StepContainer";
import {
  TimelineRendererComponent,
  TimelineRendererResult,
} from "@/app/chat/message/messageComponents/timeline/TimelineRendererComponent";
import ExpandableTextDisplay from "@/refresh-components/texts/ExpandableTextDisplay";
import Text from "@/refresh-components/texts/Text";
import { useMarkdownRenderer } from "@/app/chat/message/messageComponents/markdownUtils";

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

  // Markdown renderer for ExpandableTextDisplay
  const { renderedContent } = useMarkdownRenderer(
    fullReportContent,
    state,
    "text-text-03 font-main-ui-body"
  );

  // Stable callbacks to avoid creating new functions on every render
  const noopComplete = useCallback(() => {}, []);
  const renderReport = useCallback(() => renderedContent, [renderedContent]);

  // HIGHLIGHT mode: return raw content with header embedded in content
  if (isHighlight) {
    if (showOnlyReport) {
      return children({
        icon: null,
        status: null,
        content: (
          <div className="flex flex-col">
            <Text as="p" text02 className="text-sm mb-1">
              Research Report
            </Text>
            <ExpandableTextDisplay
              title="Research Report"
              content={fullReportContent}
              maxLines={5}
              renderContent={renderReport}
            />
          </div>
        ),
        supportsCompact: true,
      });
    }

    if (showOnlyTools) {
      const latestGroup = visibleNestedToolGroups[0];
      if (latestGroup) {
        return (
          <TimelineRendererComponent
            key={latestGroup.sub_turn_index}
            packets={latestGroup.packets}
            chatState={state}
            onComplete={noopComplete}
            animate={!stopPacketSeen && !latestGroup.isComplete}
            stopPacketSeen={stopPacketSeen}
            defaultExpanded={false}
            renderTypeOverride={RenderType.HIGHLIGHT}
            isLastStep={true}
            isHover={isHover}
          >
            {({ content }) =>
              children({
                icon: null,
                status: null,
                content,
                supportsCompact: true,
              })
            }
          </TimelineRendererComponent>
        );
      }
    }

    // Fallback: research task with header embedded
    if (researchTask) {
      return children({
        icon: null,
        status: null,
        content: (
          <div className="flex flex-col">
            <Text as="p" text02 className="text-sm mb-1">
              Research Task
            </Text>
            <div className="text-text-600 text-sm">{researchTask}</div>
          </div>
        ),
        supportsCompact: true,
      });
    }

    return children({
      icon: null,
      status: null,
      content: <></>,
      supportsCompact: true,
    });
  }

  // Build content using StepContainer pattern
  const researchAgentContent = (
    <div className="flex flex-col">
      {/* Research Task - hidden in compact mode when tools/report are active */}
      {researchTask && !showOnlyReport && !showOnlyTools && (
        <StepContainer
          stepIcon={FiTarget as FunctionComponent<IconProps>}
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
          <div className="text-text-600 text-sm">{researchTask}</div>
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
              key={group.sub_turn_index}
              packets={group.packets}
              chatState={state}
              onComplete={noopComplete}
              animate={!stopPacketSeen && !group.isComplete}
              stopPacketSeen={stopPacketSeen}
              defaultExpanded={true}
              isLastStep={isLastNestedStep}
              isHover={isHover}
            >
              {({
                icon,
                status,
                content,
                isExpanded,
                onToggle,
                isHover,
                supportsCompact,
              }) => (
                <StepContainer
                  stepIcon={icon as FunctionComponent<IconProps> | undefined}
                  header={status}
                  isExpanded={isExpanded}
                  onToggle={onToggle}
                  collapsible={true}
                  isLastStep={isLastNestedStep}
                  isFirstStep={!researchTask && index === 0}
                  isHover={isHover}
                  supportsCompact={supportsCompact}
                >
                  {content}
                </StepContainer>
              )}
            </TimelineRendererComponent>
          );
        })}

      {/* Intermediate report - hidden when tools are active in compact mode */}
      {fullReportContent && !showOnlyTools && (
        <StepContainer
          stepIcon={SvgCircle as FunctionComponent<IconProps>}
          header="Research Report"
          isLastStep={!stopPacketSeen && !isComplete}
          isFirstStep={!researchTask && nestedToolGroups.length === 0}
          isHover={isHover}
        >
          <ExpandableTextDisplay
            title="Research Report"
            content={fullReportContent}
            maxLines={5}
            renderContent={renderReport}
          />
        </StepContainer>
      )}

      {/* Done indicator - hidden in compact mode when active content */}
      {isComplete && !isLastStep && !showOnlyReport && !showOnlyTools && (
        <StepContainer
          stepIcon={SvgCheckCircle}
          header="Done"
          isLastStep={!stopPacketSeen && isLastStep}
          isFirstStep={false}
          isHover={isHover}
        />
      )}
    </div>
  );

  // Return simplified result (no icon, no status)
  return children({
    icon: null,
    status: null,
    content: researchAgentContent,
    supportsCompact: true,
  });
};
