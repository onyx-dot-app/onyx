"use client";

import React, {
  useState,
  useMemo,
  useCallback,
  FunctionComponent,
} from "react";
import { cn } from "@/lib/utils";
import { StopReason } from "@/app/app/services/streamingModels";
import { FullChatState } from "../interfaces";
import { TurnGroup } from "./transformers";
import {
  getToolName,
  getToolIcon,
  isToolComplete,
} from "../toolDisplayHelpers";
import {
  TimelineRendererComponent,
  TimelineRendererOutput,
} from "./TimelineRendererComponent";
import Tabs from "@/refresh-components/Tabs";
import { SvgBranch, SvgFold, SvgExpand } from "@opal/icons";
import { StepContainer } from "./StepContainer";
import { isResearchAgentPackets } from "@/app/app/message/messageComponents/timeline/packetHelpers";
import { IconProps } from "@/components/icons/icons";
import IconButton from "@/refresh-components/buttons/IconButton";

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
  const [isExpanded, setIsExpanded] = useState(true);
  const [isHover, setIsHover] = useState(false);
  const handleToggle = useCallback(() => setIsExpanded((prev) => !prev), []);

  // Find the active step based on selected tab
  const activeStep = useMemo(
    () => turnGroup.steps.find((step) => step.key === activeTab),
    [turnGroup.steps, activeTab]
  );

  // Memoized loading states for each step
  const loadingStates = useMemo(
    () =>
      new Map(
        turnGroup.steps.map((step) => [
          step.key,
          !stopPacketSeen &&
            step.packets.length > 0 &&
            !isToolComplete(step.packets),
        ])
      ),
    [turnGroup.steps, stopPacketSeen]
  );

  // Check if any step is a research agent (only research agents get collapse button)
  const hasResearchAgent = useMemo(
    () => turnGroup.steps.some((step) => isResearchAgentPackets(step.packets)),
    [turnGroup.steps]
  );
  //will be removed on cleanup
  // Stable callbacks to avoid creating new functions on every render
  const noopComplete = useCallback(() => {}, []);

  const renderTabContent = useCallback(
    (results: TimelineRendererOutput) => {
      if (isResearchAgentPackets(activeStep?.packets ?? [])) {
        return (
          <>
            {results.map((result, index) => (
              <React.Fragment key={index}>{result.content}</React.Fragment>
            ))}
          </>
        );
      }

      return (
        <>
          {results.map((result, index) => (
            <StepContainer
              key={index}
              stepIcon={result.icon as FunctionComponent<IconProps> | undefined}
              header={result.status}
              isExpanded={result.isExpanded}
              onToggle={result.onToggle}
              collapsible={true}
              isLastStep={index === results.length - 1 && isLastTurnGroup}
              isFirstStep={false}
              isHover={result.isHover}
            >
              {result.content}
            </StepContainer>
          ))}
        </>
      );
    },
    [activeStep?.packets, isLastTurnGroup]
  );

  return (
    <Tabs value={activeTab} onValueChange={setActiveTab}>
      <div className="flex flex-col w-full">
        <div
          className="flex w-full"
          onMouseEnter={() => setIsHover(true)}
          onMouseLeave={() => setIsHover(false)}
        >
          {/* Left column: Icon + connector line */}
          <div className="flex flex-col items-center w-9 pt-2">
            <div
              className={cn(
                "size-5 flex items-center justify-center text-text-02",
                isHover &&
                  "text-text-inverted-05 bg-background-neutral-inverted-00 rounded-full"
              )}
            >
              <SvgBranch className="w-3 h-3" />
            </div>
            {/* Connector line */}
            <div
              className={cn(
                "w-px flex-1 bg-border-01",
                isHover && "bg-border-04"
              )}
            />
          </div>

          {/* Right column: Tabs + collapse button */}
          <div
            className={cn(
              "w-full pl-1 bg-background-tint-00",
              isHover && "bg-background-tint-02"
            )}
          >
            <Tabs.List
              variant="pill"
              enableScrollArrows
              className={cn(
                isHover && "bg-background-tint-02",
                "transition-colors duration-200"
              )}
              rightContent={
                <IconButton
                  tertiary
                  onClick={handleToggle}
                  icon={isExpanded ? SvgFold : SvgExpand}
                />
              }
            >
              {turnGroup.steps.map((step) => (
                <Tabs.Trigger
                  key={step.key}
                  value={step.key}
                  variant="pill"
                  isLoading={loadingStates.get(step.key)}
                >
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
            key={`${activeTab}-${isExpanded}`}
            packets={
              !isExpanded && stopPacketSeen ? [] : activeStep?.packets ?? []
            }
            chatState={chatState}
            onComplete={noopComplete}
            animate={!stopPacketSeen}
            stopPacketSeen={stopPacketSeen}
            stopReason={stopReason}
            defaultExpanded={isExpanded}
            isLastStep={isLastTurnGroup}
            isHover={isHover}
          >
            {renderTabContent}
          </TimelineRendererComponent>
        </div>
      </div>
    </Tabs>
  );
}

export default ParallelTimelineTabs;
