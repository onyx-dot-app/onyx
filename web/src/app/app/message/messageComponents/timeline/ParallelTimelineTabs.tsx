"use client";

import React, { useState, useMemo, useCallback } from "react";
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
import { Button } from "@opal/components";
import { TimelineRow } from "@/app/app/message/messageComponents/timeline/primitives/TimelineRow";
import { TimelineSurface } from "@/app/app/message/messageComponents/timeline/primitives/TimelineSurface";
import { TimelineTopSpacer } from "@/app/app/message/messageComponents/timeline/primitives/TimelineTopSpacer";
import { TimelineStepComposer } from "./TimelineStepComposer";

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
  /** Whether this is the first turn group (affects connector line) */
  isFirstTurnGroup: boolean;
}

export function ParallelTimelineTabs({
  turnGroup,
  chatState,
  stopPacketSeen,
  stopReason,
  isLastTurnGroup,
  isFirstTurnGroup,
}: ParallelTimelineTabsProps) {
  const [activeTab, setActiveTab] = useState(turnGroup.steps[0]?.key ?? "");
  const [isExpanded, setIsExpanded] = useState(true);
  const [isHover, setIsHover] = useState(false);
  const handleToggle = useCallback(() => setIsExpanded((prev) => !prev), []);
  const handleHeaderEnter = useCallback(() => setIsHover(true), []);
  const handleHeaderLeave = useCallback(() => setIsHover(false), []);
  const topSpacerVariant = isFirstTurnGroup ? "first" : "none";
  const shouldShowResults = !(!isExpanded && stopPacketSeen);

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

  const renderTabContent = useCallback(
    (results: TimelineRendererOutput) => (
      <TimelineStepComposer
        results={results}
        isLastStep={isLastTurnGroup}
        isFirstStep={false}
        isSingleStep={false}
        collapsible={true}
      />
    ),
    [isLastTurnGroup]
  );

  const hasActivePackets = Boolean(activeStep && activeStep.packets.length > 0);
  const headerIsLast =
    isLastTurnGroup && (!shouldShowResults || !hasActivePackets);

  return (
    <Tabs value={activeTab} onValueChange={setActiveTab}>
      <div className="flex flex-col w-full">
        <TimelineRow
          railVariant="rail"
          isFirst={isFirstTurnGroup}
          isLast={headerIsLast}
          isHover={isHover}
          disableTopConnectorHover={true}
          icon={
            <div
              className={cn(
                "h-[var(--timeline-branch-icon-wrapper-size)] w-[var(--timeline-branch-icon-wrapper-size)] flex items-center justify-center text-text-02",
                isHover &&
                  "text-text-inverted-05 bg-background-neutral-inverted-00 rounded-full"
              )}
            >
              <SvgBranch className="h-[var(--timeline-branch-icon-size)] w-[var(--timeline-branch-icon-size)]" />
            </div>
          }
        >
          <TimelineSurface
            className="flex-1 flex flex-col"
            isHover={isHover}
            roundedBottom={headerIsLast}
          >
            <TimelineTopSpacer variant={topSpacerVariant} />

            <div
              className="flex items-center min-h-[var(--timeline-step-header-height)] pl-[var(--timeline-header-padding-left)] pr-[var(--timeline-header-padding-right)]"
              onMouseEnter={handleHeaderEnter}
              onMouseLeave={handleHeaderLeave}
            >
              <Tabs.List
                variant="pill"
                enableScrollArrows
                className={cn(
                  isHover && "bg-background-tint-02",
                  "transition-colors duration-200"
                )}
                rightContent={
                  <Button
                    prominence="tertiary"
                    size="sm"
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
          </TimelineSurface>
        </TimelineRow>

        {shouldShowResults && activeStep && (
          <TimelineRendererComponent
            key={`${activeTab}-${isExpanded}`}
            packets={activeStep.packets}
            chatState={chatState}
            animate={!stopPacketSeen}
            stopPacketSeen={stopPacketSeen}
            stopReason={stopReason}
            defaultExpanded={isExpanded}
            isLastStep={isLastTurnGroup}
            isHover={isHover}
          >
            {renderTabContent}
          </TimelineRendererComponent>
        )}
      </div>
    </Tabs>
  );
}

export default ParallelTimelineTabs;
