"use client";

import React, { useState, useMemo, FunctionComponent } from "react";
import {
  StopReason,
  PacketType,
  Packet,
} from "@/app/chat/services/streamingModels";
import { FullChatState } from "../interfaces";
import { TurnGroup } from "./transformers";
import { getToolName, getToolIcon } from "../toolDisplayHelpers";
import { TimelineRendererComponent } from "./TimelineRendererComponent";
import Tabs from "@/refresh-components/Tabs";
import { SvgBranch } from "@opal/icons";
import { StepContainer } from "./AgentTimeline";
import { IconProps } from "@/components/icons/icons";

/** Check if packets are for ResearchAgentRenderer (which has its own StepContainer layout) */
const isResearchAgentPackets = (packets: Packet[]) =>
  packets.some((p) => p.obj.type === PacketType.RESEARCH_AGENT_START);

export interface ParallelTimelineTabsProps {
  /** Turn group containing parallel steps */
  turnGroup: TurnGroup;
  /** Chat state for rendering content */
  chatState: FullChatState;
  /** Whether the stop packet has been seen */
  stopPacketSeen: boolean;
  /** Reason for stopping (if stopped) */
  stopReason?: StopReason;
  /** Whether this is the last turn group (affects connector line) */
  isLastTurnGroup: boolean;
  /** Additional class names */
  className?: string;
}

export function ParallelTimelineTabs({
  turnGroup,
  chatState,
  stopPacketSeen,
  stopReason,
  isLastTurnGroup,
  className,
}: ParallelTimelineTabsProps) {
  const [activeTab, setActiveTab] = useState(turnGroup.steps[0]?.key ?? "");

  // Find the active step based on selected tab
  const activeStep = useMemo(
    () => turnGroup.steps.find((step) => step.key === activeTab),
    [turnGroup.steps, activeTab]
  );

  return (
    <Tabs value={activeTab} onValueChange={setActiveTab}>
      <div className="flex flex-col w-full">
        <div className="flex w-full">
          {/* Left column: Icon + connector line */}
          <div className="flex flex-col items-center w-9 pt-2">
            <div className="size-4 flex items-center justify-center stroke-text-02">
              <SvgBranch className="w-4 h-4" />
            </div>
            {/* Connector line */}
            <div className="w-px flex-1 bg-border-01" />
          </div>

          {/* Right column: Tabs */}
          <div className="flex-1">
            <Tabs.List variant="pill">
              {turnGroup.steps.map((step) => (
                <Tabs.Trigger key={step.key} value={step.key} variant="pill">
                  <span className="flex items-center gap-1.5">
                    {getToolIcon(step.packets)}
                    {getToolName(step.packets)}
                  </span>
                </Tabs.Trigger>
              ))}
            </Tabs.List>
          </div>
        </div>
        <div className="w-full">
          <TimelineRendererComponent
            packets={activeStep?.packets ?? []}
            chatState={chatState}
            onComplete={() => {}}
            animate={!stopPacketSeen}
            stopPacketSeen={stopPacketSeen}
            stopReason={stopReason}
            defaultExpanded={true}
            isLastStep={isLastTurnGroup}
          >
            {({ icon, status, content, isExpanded, onToggle, isLastStep }) =>
              isResearchAgentPackets(activeStep?.packets ?? []) ? (
                // ResearchAgentRenderer has its own StepContainer layout
                content
              ) : (
                <StepContainer
                  stepIcon={icon as FunctionComponent<IconProps> | undefined}
                  header={status}
                  isExpanded={isExpanded}
                  onToggle={onToggle}
                  collapsible={true}
                  isLastStep={isLastStep}
                  isFirstStep={false}
                >
                  {content}
                </StepContainer>
              )
            }
          </TimelineRendererComponent>
        </div>
      </div>
    </Tabs>
  );
}

export default ParallelTimelineTabs;
