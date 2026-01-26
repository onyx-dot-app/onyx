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
} from "@/app/chat/message/messageComponents/interfaces";
import { getToolName } from "@/app/chat/message/messageComponents/toolDisplayHelpers";
import { StepContainer } from "@/app/chat/message/messageComponents/timeline/StepContainer";
import {
  TimelineRendererComponent,
  TimelineRendererResult,
} from "@/app/chat/message/messageComponents/timeline/TimelineRendererComponent";
import ExpandableTextDisplay from "@/refresh-components/texts/ExpandableTextDisplay";
import { useMarkdownRenderer } from "@/app/chat/message/messageComponents/markdownUtils";

interface NestedToolGroup {
  sub_turn_index: number;
  toolType: string;
  status: string;
  isComplete: boolean;
  packets: Packet[];
}

/**
 * Renderer for research agent steps in deep research.
 * Segregates packets by tool and uses StepContainer + TimelineRendererComponent.
 */
export const ResearchAgentRenderer: MessageRenderer<
  ResearchAgentPacket,
  FullChatState
> = ({
  packets,
  state,
  onComplete,
  stopPacketSeen,
  isLastStep = true,
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

  // Check completion from parent packets
  const isComplete = parentPackets.some(
    (p) => p.obj.type === PacketType.SECTION_END
  );
  const hasCalledCompleteRef = useRef(false);

  useEffect(() => {
    if (isComplete && !hasCalledCompleteRef.current) {
      hasCalledCompleteRef.current = true;
      onComplete();
    }
  }, [isComplete, onComplete]);

  // Build report content from parent packets
  const fullReportContent = parentPackets
    .map((packet) => {
      if (packet.obj.type === PacketType.INTERMEDIATE_REPORT_DELTA) {
        return (packet.obj as IntermediateReportDelta).content;
      }
      return "";
    })
    .join("");

  // Markdown renderer for ExpandableTextDisplay
  const { renderedContent } = useMarkdownRenderer(
    fullReportContent,
    state,
    "text-text-03 font-main-ui-body"
  );

  // Stable callbacks to avoid creating new functions on every render
  const noopComplete = useCallback(() => {}, []);
  const renderReport = useCallback(() => renderedContent, [renderedContent]);

  // Build content using StepContainer pattern
  const researchAgentContent = (
    <div className="flex flex-col">
      {/* Research Task - using StepContainer (collapsible) */}
      {researchTask && (
        <StepContainer
          stepIcon={FiTarget as FunctionComponent<IconProps>}
          header="Research Task"
          collapsible={true}
          isLastStep={
            nestedToolGroups.length === 0 && !fullReportContent && !isComplete
          }
        >
          <div className="text-text-600 text-sm">{researchTask}</div>
        </StepContainer>
      )}

      {/* Nested tool calls - using TimelineRendererComponent + StepContainer */}
      {nestedToolGroups.map((group, index) => {
        const isLastNestedStep =
          index === nestedToolGroups.length - 1 &&
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
          >
            {({ icon, status, content, isExpanded, onToggle }) => (
              <StepContainer
                stepIcon={icon as FunctionComponent<IconProps> | undefined}
                header={status}
                isExpanded={isExpanded}
                onToggle={onToggle}
                collapsible={true}
                isLastStep={isLastNestedStep}
                isFirstStep={!researchTask && index === 0}
              >
                {content}
              </StepContainer>
            )}
          </TimelineRendererComponent>
        );
      })}

      {/* Intermediate report - using ExpandableTextDisplay */}
      {fullReportContent && (
        <StepContainer
          stepIcon={SvgCircle as FunctionComponent<IconProps>}
          header="Research Report"
          isLastStep={!isComplete}
          isFirstStep={!researchTask && nestedToolGroups.length === 0}
        >
          <ExpandableTextDisplay
            title="Research Report"
            content={fullReportContent}
            maxLines={5}
            renderContent={renderReport}
          />
        </StepContainer>
      )}

      {/* Done indicator at end of research agent */}
      {isComplete && !isLastStep && (
        <StepContainer
          stepIcon={SvgCheckCircle}
          header="Done"
          isLastStep={isLastStep}
          isFirstStep={false}
        />
      )}
    </div>
  );

  // Return simplified result (no icon, no status)
  return children({
    icon: null,
    status: null,
    content: researchAgentContent,
  });
};
