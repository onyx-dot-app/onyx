import React, { useEffect, useMemo, useState, useRef } from "react";
import { FiCircle, FiTarget, FiMessageSquare } from "react-icons/fi";
import { SvgChevronDown } from "@opal/icons";
import { cn } from "@/lib/utils";
import { FaRobot } from "react-icons/fa";

import {
  PacketType,
  Packet,
  AgentToolPacket,
  AgentToolStart,
  AgentToolTask,
  AgentToolResult,
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
 * Renderer for agent tool (sub-agent delegation) steps.
 * Shows the delegated task, nested tool calls from the sub-agent, and the final answer.
 */
export const AgentToolRenderer: MessageRenderer<
  AgentToolPacket,
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
  // Extract data from packets
  const startPacket = packets.find(
    (p) => p.obj.type === PacketType.AGENT_TOOL_START
  );
  const taskPacket = packets.find(
    (p) => p.obj.type === PacketType.AGENT_TOOL_TASK
  );
  const resultPacket = packets.find(
    (p) => p.obj.type === PacketType.AGENT_TOOL_RESULT
  );

  const agentName = startPacket
    ? (startPacket.obj as AgentToolStart).agent_name
    : taskPacket
      ? (taskPacket.obj as AgentToolTask).agent_name
      : "Agent";
  const toolName = startPacket
    ? (startPacket.obj as AgentToolStart).tool_name
    : `Call ${agentName}`;
  const task = taskPacket ? (taskPacket.obj as AgentToolTask).task : "";
  const answer = resultPacket
    ? (resultPacket.obj as AgentToolResult).answer
    : "";

  // Separate parent packets (no sub_turn_index) from nested tool packets
  const { parentPackets, nestedToolGroups } = useMemo(() => {
    const parent: Packet[] = [];
    const nestedBySubTurn = new Map<number, Packet[]>();

    packets.forEach((packet) => {
      const subTurnIndex = packet.placement.sub_turn_index;
      if (subTurnIndex === undefined || subTurnIndex === null) {
        // Parent-level packet (agent tool start, task, result, etc.)
        parent.push(packet);
      } else {
        // Nested tool packet from sub-agent
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

  // Check if complete - agent tool is complete when parent packets have SECTION_END
  const isComplete = parentPackets.some(
    (p) => p.obj.type === PacketType.SECTION_END
  );
  const hasAnswer = Boolean(answer);
  const [isExpanded, toggleExpanded] = useState(true);
  const hasCalledCompleteRef = useRef(false);

  // Call onComplete when agent tool is complete
  useEffect(() => {
    if (isComplete && !hasCalledCompleteRef.current) {
      hasCalledCompleteRef.current = true;
      onComplete();
    }
  }, [isComplete, onComplete]);

  // Use markdown renderer for the answer
  const { renderedContent: renderedAnswer } = useMarkdownRenderer(
    answer,
    state,
    "text-text-03 font-main-ui-body"
  );

  // Determine status text
  let statusText: string;
  if (isComplete) {
    statusText = `${agentName} completed`;
  } else if (hasAnswer) {
    statusText = "Received response";
  } else if (nestedToolGroups.length > 0) {
    const activeTools = nestedToolGroups.filter((g) => !g.isComplete);
    if (activeTools.length > 0) {
      statusText =
        activeTools[activeTools.length - 1]?.toolType ?? "Processing";
    } else {
      statusText = "Processing";
    }
  } else if (task) {
    statusText = `Delegating to ${agentName}`;
  } else {
    statusText = `Calling ${agentName}`;
  }

  // Render nested tool using RendererComponent
  const renderNestedTool = (
    group: NestedToolGroup,
    index: number,
    totalGroups: number
  ) => {
    const isLastItem = index === totalGroups - 1 && !hasAnswer;
    const isLoading = !stopPacketSeen && !group.isComplete && !isComplete;
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

  // Total steps = task (1) + nested tool groups + answer (if present)
  const stepCount = 1 + nestedToolGroups.length + (hasAnswer ? 1 : 0);

  // Custom status element with toggle chevron
  // Using span instead of div to allow nesting inside <p> tags
  const statusElement = (
    <span
      className="flex items-center justify-between gap-2 cursor-pointer group w-full"
      onClick={() => toggleExpanded(!isExpanded)}
    >
      <span>{statusText}</span>
      <span className="flex items-center gap-2">
        {stepCount > 0 && (
          <span className="text-text-500 text-xs">{stepCount} Steps</span>
        )}
        <SvgChevronDown
          className={cn(
            "w-4 h-4 stroke-text-400 transition-transform duration-150 ease-in-out",
            !isExpanded && "rotate-[-90deg]"
          )}
        />
      </span>
    </span>
  );

  const agentToolContent = (
    <div className="text-text-600 text-sm overflow-hidden">
      {/* Collapsible content */}
      <div
        className={cn(
          "overflow-hidden transition-all duration-200 ease-in-out",
          isExpanded ? "max-h-[2000px] opacity-100 mt-2" : "max-h-0 opacity-0"
        )}
      >
        {/* First item: Delegated Task */}
        {task && (
          <div className="space-y-0.5 mb-1">
            <NestedToolItemRow
              icon={({ size }) => <FiTarget size={size} />}
              content={
                <div className="text-text-600 text-sm break-words whitespace-normal">
                  {task}
                </div>
              }
              status="Delegated Task"
              isLastItem={nestedToolGroups.length === 0 && !hasAnswer}
              isLoading={false}
            />
          </div>
        )}

        {/* Render nested tool calls from sub-agent */}
        {nestedToolGroups.length > 0 && (
          <div className="space-y-0.5">
            {nestedToolGroups.map((group, index) =>
              renderNestedTool(group, index, nestedToolGroups.length)
            )}
          </div>
        )}

        {/* Render final answer */}
        {hasAnswer && (
          <div className="space-y-0.5 mt-1">
            <NestedToolItemRow
              icon={({ size }) => <FiMessageSquare size={size} />}
              content={
                <div className="text-text-600 text-sm max-h-[9rem] overflow-y-auto">
                  {renderedAnswer}
                </div>
              }
              status={`${agentName} Response`}
              isLastItem={true}
              isLoading={false}
            />
          </div>
        )}
      </div>
    </div>
  );

  return children({
    icon: FaRobot,
    status: statusElement,
    content: agentToolContent,
    expandedText: agentToolContent,
  });
};
