import React, { useEffect, useMemo, useState, useRef } from "react";
import { FiUsers, FiCircle, FiTarget } from "react-icons/fi";
import { SvgChevronDown } from "@opal/icons";
import { cn } from "@/lib/utils";

import {
  PacketType,
  Packet,
  ResearchAgentPacket,
  ResearchAgentStart,
  IntermediateReportDelta,
} from "../../../services/streamingModels";
import { MessageRenderer, FullChatState, RendererResult } from "../interfaces";
import { RendererComponent } from "../renderMessageComponent";
import { getToolName } from "../toolDisplayHelpers";
import { STANDARD_TEXT_COLOR } from "../constants";
import Text from "@/refresh-components/texts/Text";
import { useMarkdownRenderer } from "../markdownUtils";

interface NestedToolGroup {
  sub_turn_index: number;
  toolType: string;
  status: string;
  isComplete: boolean;
  packets: Packet[];
}

/**
 * Simple row component for rendering nested tool content
 */
function NestedToolItemRow({
  icon,
  content,
  status,
  isLastItem,
  isLoading,
  isCancelled,
}: {
  icon: ((props: { size: number }) => React.JSX.Element) | null;
  content: React.JSX.Element | string;
  status: string | React.JSX.Element | null;
  isLastItem: boolean;
  isLoading?: boolean;
  isCancelled?: boolean;
}) {
  return (
    <div className="relative">
      {!isLastItem && (
        <div
          className="absolute w-px bg-background-tint-04 z-0"
          style={{ left: "10px", top: "20px", bottom: "0" }}
        />
      )}
      <div
        className={cn(
          "flex items-start gap-2",
          STANDARD_TEXT_COLOR,
          "relative z-10"
        )}
      >
        <div className="flex flex-col items-center w-5">
          <div className="flex-shrink-0 flex items-center justify-center w-5 h-5 bg-background rounded-full">
            {icon ? (
              <div className={cn(isLoading && "text-shimmer-base")}>
                {icon({ size: 14 })}
              </div>
            ) : (
              <FiCircle className="w-2 h-2 fill-current text-text-300" />
            )}
          </div>
        </div>
        <div
          className={cn(
            "flex-1 min-w-0 overflow-hidden",
            !isLastItem && "pb-4"
          )}
        >
          <Text
            as="p"
            text02
            className={cn(
              "text-sm mb-1",
              isLoading && !isCancelled && "loading-text"
            )}
          >
            {status}
          </Text>
          <div className="text-sm text-text-600 overflow-hidden">{content}</div>
        </div>
      </div>
    </div>
  );
}

/**
 * Renderer for research agent steps in deep research.
 * Shows the research task, nested tool calls, and streams the intermediate report.
 */
export const ResearchAgentRenderer: MessageRenderer<
  ResearchAgentPacket,
  FullChatState
> = ({
  packets,
  state,
  onComplete,
  renderType,
  animate,
  stopPacketSeen,
  children,
}) => {
  // Extract the research task from the start packet
  const startPacket = packets.find(
    (p) => p.obj.type === PacketType.RESEARCH_AGENT_START
  );
  const researchTask = startPacket
    ? (startPacket.obj as ResearchAgentStart).research_task
    : "";

  // Separate parent packets (no sub_turn_index or sub_turn_index === undefined)
  // from nested tool packets (sub_turn_index is a number)
  const { parentPackets, nestedToolGroups } = useMemo(() => {
    const parent: Packet[] = [];
    const nestedBySubTurn = new Map<number, Packet[]>();

    packets.forEach((packet) => {
      const subTurnIndex = packet.placement.sub_turn_index;
      if (subTurnIndex === undefined || subTurnIndex === null) {
        // Parent-level packet (research agent start, intermediate report, etc.)
        parent.push(packet);
      } else {
        // Nested tool packet
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
        // Check for completion: SECTION_END for regular tools, REASONING_DONE for reasoning/think tools
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

  // Check if report has started (from parent packets only)
  const hasReportStarted = parentPackets.some(
    (p) => p.obj.type === PacketType.INTERMEDIATE_REPORT_START
  );

  // Check if complete - research agent is complete when parent packets have SECTION_END
  // (not when nested tools have SECTION_END)
  const isComplete = parentPackets.some(
    (p) => p.obj.type === PacketType.SECTION_END
  );
  const [isExpanded, toggleExpanded] = useState(true);
  const hasCalledCompleteRef = useRef(false);

  // Call onComplete when research agent is complete
  useEffect(() => {
    if (isComplete && !hasCalledCompleteRef.current) {
      hasCalledCompleteRef.current = true;
      onComplete();
    }
  }, [isComplete, onComplete]);

  // Get the full report content from parent packets only
  const fullReportContent = parentPackets
    .map((packet) => {
      if (packet.obj.type === PacketType.INTERMEDIATE_REPORT_DELTA) {
        return (packet.obj as IntermediateReportDelta).content;
      }
      return "";
    })
    .join("");

  const reportContent = fullReportContent;

  // Use markdown renderer to render the report content
  const { renderedContent: renderedReportContent } = useMarkdownRenderer(
    reportContent,
    state,
    "text-text-03 font-main-ui-body"
  );

  // Determine status text
  let statusText: string;
  if (isComplete) {
    statusText = "Research complete";
  } else if (hasReportStarted) {
    statusText = "Writing report";
  } else if (nestedToolGroups.length > 0) {
    const activeTools = nestedToolGroups.filter((g) => !g.isComplete);
    if (activeTools.length > 0) {
      statusText =
        activeTools[activeTools.length - 1]?.toolType ?? "Processing";
    } else {
      statusText = "Processing";
    }
  } else {
    statusText = "Researching";
  }

  // Render nested tool using RendererComponent for full detailed output
  const renderNestedTool = (
    group: NestedToolGroup,
    index: number,
    totalGroups: number
  ) => {
    const isLastItem = index === totalGroups - 1;
    // If stopPacketSeen is true, loading is false (cancelled state)
    const isLoading = !stopPacketSeen && !group.isComplete && !isComplete;
    // Tool is cancelled if stop was triggered and it's not complete
    const isCancelled = stopPacketSeen && !group.isComplete;

    return (
      <RendererComponent
        key={group.sub_turn_index}
        packets={group.packets}
        chatState={state}
        onComplete={() => {}}
        animate={false}
        stopPacketSeen={stopPacketSeen || false}
        useShortRenderer={false}
      >
        {(result: RendererResult) => (
          <NestedToolItemRow
            icon={result.icon}
            content={result.content}
            status={result.status}
            isLastItem={isLastItem}
            isLoading={isLoading}
            isCancelled={isCancelled}
          />
        )}
      </RendererComponent>
    );
  };

  // Total steps = research task (1) + nested tool groups count
  const stepCount = 1 + nestedToolGroups.length;

  // Custom status element with toggle chevron
  const statusElement = (
    <div
      className="flex items-center justify-between gap-2 cursor-pointer group w-full"
      onClick={() => toggleExpanded(!isExpanded)}
    >
      <span>{statusText}</span>
      <div className="flex items-center gap-2">
        {stepCount > 0 && (
          <span className="text-text-500 text-xs">{stepCount} Steps</span>
        )}
        <SvgChevronDown
          className={cn(
            "w-4 h-4 stroke-text-400 transition-transform duration-150 ease-in-out",
            !isExpanded && "rotate-[-90deg]"
          )}
        />
      </div>
    </div>
  );

  const researchAgentContent = (
    <div className="text-text-600 text-sm overflow-hidden">
      {/* Collapsible content */}
      <div
        className={cn(
          "overflow-hidden transition-all duration-200 ease-in-out",
          isExpanded ? "max-h-[2000px] opacity-100 mt-2" : "max-h-0 opacity-0"
        )}
      >
        {/* First item: Research Task */}
        {researchTask && (
          <div className="space-y-0.5 mb-1">
            <NestedToolItemRow
              icon={({ size }) => <FiTarget size={size} />}
              content={
                <div className="text-text-600 text-sm break-words whitespace-normal">
                  {researchTask}
                </div>
              }
              status="Research Task"
              isLastItem={nestedToolGroups.length === 0 && !reportContent}
              isLoading={false}
            />
          </div>
        )}

        {/* Render nested tool calls */}
        {nestedToolGroups.length > 0 && (
          <div className="space-y-0.5">
            {nestedToolGroups.map((group, index) =>
              renderNestedTool(group, index, nestedToolGroups.length)
            )}
          </div>
        )}

        {/* Render intermediate report */}
        {reportContent && (
          <div className="mt-6 text-sm text-text-500 max-h-[9rem] overflow-y-auto">
            {renderedReportContent}
          </div>
        )}
      </div>
    </div>
  );

  return children({
    icon: FiUsers,
    status: statusElement,
    content: researchAgentContent,
    expandedText: researchAgentContent,
  });
};
