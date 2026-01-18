"use client";

import React, { FunctionComponent, useState, useMemo, useEffect } from "react";
import {
  PacketType,
  StopReason,
  Packet,
} from "@/app/chat/services/streamingModels";
import { FullChatState } from "../interfaces";
import { TurnGroup } from "./transformers";
import { cn } from "@/lib/utils";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import { SvgFold, SvgExpand, SvgCheckCircle, SvgStopCircle } from "@opal/icons";
import Button from "@/refresh-components/buttons/Button";
import IconButton from "@/refresh-components/buttons/IconButton";
import { IconProps } from "@opal/types";
import { TimelineRendererComponent } from "./TimelineRendererComponent";
import Text from "@/refresh-components/texts/Text";
import { useTimelineHeader } from "./useTimelineHeader";
import { ParallelTimelineTabs } from "./ParallelTimelineTabs";
import { getToolIconByName } from "../toolDisplayHelpers";

const isResearchAgentPackets = (packets: Packet[]) =>
  packets.some((p) => p.obj.type === PacketType.RESEARCH_AGENT_START);

// =============================================================================
// Header Sub-Components
// =============================================================================

interface StreamingHeaderProps {
  headerText: string;
  collapsible: boolean;
  buttonTitle?: string;
  isExpanded: boolean;
  onToggle: () => void;
}

/** Header shown during streaming - shimmer text with current activity */
function StreamingHeader({
  headerText,
  collapsible,
  buttonTitle,
  isExpanded,
  onToggle,
}: StreamingHeaderProps) {
  return (
    <>
      <Text
        as="p"
        mainUiAction
        text03
        className="animate-shimmer bg-[length:200%_100%] bg-[linear-gradient(90deg,var(--shimmer-base)_10%,var(--shimmer-highlight)_40%,var(--shimmer-base)_70%)] bg-clip-text text-transparent"
      >
        {headerText}
      </Text>
      {collapsible &&
        (buttonTitle ? (
          <Button
            tertiary
            onClick={onToggle}
            rightIcon={isExpanded ? SvgFold : SvgExpand}
            aria-expanded={isExpanded}
          >
            {buttonTitle}
          </Button>
        ) : (
          <IconButton
            tertiary
            onClick={onToggle}
            icon={isExpanded ? SvgFold : SvgExpand}
            aria-label={isExpanded ? "Collapse timeline" : "Expand timeline"}
            aria-expanded={isExpanded}
          />
        ))}
    </>
  );
}

interface CollapsedHeaderProps {
  uniqueTools: Array<{ key: string; name: string; icon: React.JSX.Element }>;
  totalSteps: number;
  collapsible: boolean;
  onToggle: () => void;
}

/** Header shown when completed + collapsed - tools summary + step count */
function CollapsedHeader({
  uniqueTools,
  totalSteps,
  collapsible,
  onToggle,
}: CollapsedHeaderProps) {
  return (
    <>
      <div className="flex items-center gap-2">
        {uniqueTools.map((tool) => (
          <div
            key={tool.key}
            className="inline-flex items-center gap-1 rounded-08 p-1 bg-background-tint-02"
          >
            {tool.icon}
            <Text as="span" secondaryBody text04>
              {tool.name}
            </Text>
          </div>
        ))}
      </div>
      {collapsible && (
        <Button
          tertiary
          onClick={onToggle}
          rightIcon={SvgExpand}
          aria-label="Expand timeline"
          aria-expanded={false}
        >
          {totalSteps} {totalSteps === 1 ? "step" : "steps"}
        </Button>
      )}
    </>
  );
}

interface ExpandedHeaderProps {
  collapsible: boolean;
  onToggle: () => void;
  // duration?: string; // For future: "Thought for X time"
}

/** Header shown when completed + expanded - "Thought for X time" */
function ExpandedHeader({ collapsible, onToggle }: ExpandedHeaderProps) {
  return (
    <>
      <Text as="p" mainUiAction text03>
        Thought for some time
      </Text>
      {collapsible && (
        <IconButton
          tertiary
          onClick={onToggle}
          icon={SvgFold}
          aria-label="Collapse timeline"
          aria-expanded={true}
        />
      )}
    </>
  );
}

interface StoppedHeaderProps {
  totalSteps: number;
  collapsible: boolean;
  isExpanded: boolean;
  onToggle: () => void;
}

/** Header shown when user stopped/cancelled - "Stopped Thinking" + steps */
function StoppedHeader({
  totalSteps,
  collapsible,
  isExpanded,
  onToggle,
}: StoppedHeaderProps) {
  return (
    <>
      <Text as="p" mainUiAction text03>
        Stopped Thinking
      </Text>
      {collapsible && (
        <Button
          tertiary
          onClick={onToggle}
          rightIcon={isExpanded ? SvgFold : SvgExpand}
          aria-label={isExpanded ? "Collapse timeline" : "Expand timeline"}
          aria-expanded={isExpanded}
        >
          {totalSteps} {totalSteps === 1 ? "step" : "steps"}
        </Button>
      )}
    </>
  );
}

// =============================================================================
// Main Component
// =============================================================================

export interface AgentTimelineProps {
  /** Turn groups from usePacketProcessor */
  turnGroups: TurnGroup[];
  /** Chat state for rendering content */
  chatState: FullChatState;
  /** Whether the stop packet has been seen */
  stopPacketSeen?: boolean;
  /** Reason for stopping (if stopped) */
  stopReason?: StopReason;
  /** Whether final answer is coming (affects last connector) */
  finalAnswerComing?: boolean;
  /** Whether there is display content after timeline */
  hasDisplayContent?: boolean;
  /** Content to render after timeline (final message + toolbar) - slot pattern */
  children?: React.ReactNode;
  /** Whether the timeline is collapsible */
  collapsible?: boolean;
  /** Title of the button to toggle the timeline */
  buttonTitle?: string;
  /** Additional class names */
  className?: string;
  /** Test ID for e2e testing */
  "data-testid"?: string;
  /** Unique tool names used (pre-computed from packet processor for performance) */
  uniqueToolNames?: string[];
}

export function AgentTimeline({
  turnGroups,
  chatState,
  stopPacketSeen = false,
  stopReason,
  finalAnswerComing = false,
  hasDisplayContent = false,
  collapsible = true,
  buttonTitle,
  className,
  "data-testid": testId,
  uniqueToolNames = [],
}: AgentTimelineProps) {
  const [isExpanded, setIsExpanded] = useState(!stopPacketSeen);
  const handleToggle = () => setIsExpanded((prev) => !prev);

  // Collapse when streaming completes (stopPacketSeen transitions to true)
  // Note: Does not re-expand if stopPacketSeen changes back to false -
  // user controls expansion after streaming completes
  useEffect(() => {
    if (stopPacketSeen) {
      setIsExpanded(false);
    }
  }, [stopPacketSeen]);
  const { headerText, hasPackets, userStopped } = useTimelineHeader(
    turnGroups,
    stopReason
  );

  // Calculate total steps across all turn groups to determine if we should hide StepContainer header
  const totalSteps = turnGroups.reduce((acc, tg) => acc + tg.steps.length, 0);
  const isSingleStep = totalSteps === 1 && !userStopped;

  // Use pre-computed unique tools from packet processor (performance optimization)
  const uniqueTools = useMemo(
    () =>
      uniqueToolNames.map((name) => ({
        key: name,
        name,
        icon: getToolIconByName(name),
      })),
    [uniqueToolNames]
  );

  // Check if last step is a research agent (which handles its own Done)
  const lastTurnGroup = turnGroups[turnGroups.length - 1];
  const lastStep = lastTurnGroup?.steps[lastTurnGroup.steps.length - 1];
  const lastStepIsResearchAgent = lastStep
    ? isResearchAgentPackets(lastStep.packets)
    : false;

  // Show "Done" indicator when:
  // 1. stopPacketSeen is true (timeline is complete)
  // 2. isExpanded is true (user can see the timeline)
  // 3. NOT userStopped (user didn't cancel)
  // 4. Last step is NOT a research agent (they handle their own Done)
  const showDoneIndicator =
    stopPacketSeen && isExpanded && !userStopped && !lastStepIsResearchAgent;

  // Determine which header to render based on state
  const renderHeader = () => {
    // STATE 1: Streaming - show shimmer text with current activity
    if (!stopPacketSeen) {
      return (
        <StreamingHeader
          headerText={headerText}
          collapsible={collapsible}
          buttonTitle={buttonTitle}
          isExpanded={isExpanded}
          onToggle={handleToggle}
        />
      );
    }

    // STATE 2: User Stopped - show "Stopped Thinking" + steps
    if (userStopped) {
      return (
        <StoppedHeader
          totalSteps={totalSteps}
          collapsible={collapsible}
          isExpanded={isExpanded}
          onToggle={handleToggle}
        />
      );
    }

    // STATE 3: Completed + Collapsed - show tools summary
    if (!isExpanded) {
      return (
        <CollapsedHeader
          uniqueTools={uniqueTools}
          totalSteps={totalSteps}
          collapsible={collapsible}
          onToggle={handleToggle}
        />
      );
    }

    // STATE 4: Completed + Expanded - show "Thought for X time"
    return <ExpandedHeader collapsible={collapsible} onToggle={handleToggle} />;
  };

  if (!hasPackets && !hasDisplayContent) {
    return (
      <div className={cn("flex flex-col", className)}>
        <div className="flex w-full h-9">
          <div className="flex justify-center items-center size-9">
            <AgentAvatar agent={chatState.assistant} size={24} />
          </div>
          <div className="flex w-full h-full items-center px-2">
            <Text
              as="p"
              mainUiAction
              text03
              className="animate-shimmer bg-[length:200%_100%] bg-[linear-gradient(90deg,var(--shimmer-base)_10%,var(--shimmer-highlight)_40%,var(--shimmer-base)_70%)] bg-clip-text text-transparent"
            >
              {headerText}
            </Text>
          </div>
        </div>
      </div>
    );
  }

  if (hasDisplayContent && !hasPackets) {
    return (
      <div className={cn("flex flex-col", className)}>
        <div className="flex w-full h-9">
          <div className="flex justify-center items-center size-9">
            <AgentAvatar agent={chatState.assistant} size={24} />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={cn("flex flex-col", className)}>
      <div className="flex w-full h-9">
        <div className="flex justify-center items-center size-9">
          <AgentAvatar agent={chatState.assistant} size={24} />
        </div>
        <div
          className={cn(
            "flex w-full h-full items-center justify-between px-2",
            // Background for: streaming, user stopped, or expanded
            (!stopPacketSeen || userStopped || isExpanded) &&
              "bg-background-tint-00 rounded-t-12",
            // Bottom rounded when not expanded
            !isExpanded && "rounded-b-12"
          )}
        >
          {renderHeader()}
        </div>
      </div>
      {isExpanded && (
        <div className="w-full">
          {turnGroups.map((turnGroup, turnIdx) =>
            turnGroup.isParallel ? (
              <ParallelTimelineTabs
                key={turnGroup.turnIndex}
                turnGroup={turnGroup}
                chatState={chatState}
                stopPacketSeen={stopPacketSeen}
                stopReason={stopReason}
                isLastTurnGroup={turnIdx === turnGroups.length - 1}
              />
            ) : (
              turnGroup.steps.map((step, stepIdx) => {
                const stepIsLast =
                  turnIdx === turnGroups.length - 1 &&
                  stepIdx === turnGroup.steps.length - 1 &&
                  !showDoneIndicator &&
                  !userStopped;
                const stepIsFirst = turnIdx === 0 && stepIdx === 0;

                return (
                  <TimelineRendererComponent
                    key={step.key}
                    packets={step.packets}
                    chatState={chatState}
                    onComplete={() => {}}
                    animate={!stopPacketSeen}
                    stopPacketSeen={stopPacketSeen}
                    stopReason={stopReason}
                    defaultExpanded={true}
                    isLastStep={stepIsLast}
                  >
                    {({
                      icon,
                      status,
                      content,
                      isExpanded,
                      onToggle,
                      isLastStep,
                    }) =>
                      isResearchAgentPackets(step.packets) ? (
                        content
                      ) : (
                        <StepContainer
                          stepIcon={
                            icon as FunctionComponent<IconProps> | undefined
                          }
                          header={status}
                          isExpanded={isExpanded}
                          onToggle={onToggle}
                          collapsible={true}
                          isLastStep={isLastStep}
                          isFirstStep={stepIsFirst}
                          hideHeader={isSingleStep}
                        >
                          {content}
                        </StepContainer>
                      )
                    }
                  </TimelineRendererComponent>
                );
              })
            )
          )}

          {/* Done indicator at bottom of expanded timeline */}
          {stopPacketSeen && isExpanded && !userStopped && (
            <StepContainer
              stepIcon={SvgCheckCircle}
              header="Done"
              isLastStep={true}
              isFirstStep={false}
            >
              {null}
            </StepContainer>
          )}

          {/* Stopped indicator when user cancelled */}
          {stopPacketSeen && isExpanded && userStopped && (
            <StepContainer
              stepIcon={SvgStopCircle}
              header="Stopped"
              isLastStep={true}
              isFirstStep={false}
            >
              {null}
            </StepContainer>
          )}
        </div>
      )}
    </div>
  );
}

export interface StepContainerProps {
  /** Main content */
  children?: React.ReactNode;
  /** Step icon component */
  stepIcon?: FunctionComponent<IconProps>;
  /** Header left slot - accepts any component */
  header?: React.ReactNode;
  /** Time/duration string to display (e.g., "2.3s") */
  buttonTitle?: string;
  /** Controlled expanded state */
  isExpanded?: boolean;
  /** Toggle callback for controlled mode */
  onToggle?: () => void;
  /** Whether collapsible control is shown */
  collapsible?: boolean;
  /** Additional class names */
  className?: string;
  /** Whether this is the last step */
  isLastStep?: boolean;
  /** Whether this is the first step (no top connector, uses pt-2 instead) */
  isFirstStep?: boolean;
  /** Whether to hide the header (for single-step timelines) */
  hideHeader?: boolean;
}

export function StepContainer({
  children,
  stepIcon: StepIconComponent,
  header,
  buttonTitle,
  isExpanded = true,
  onToggle,
  collapsible = true,
  isLastStep = false,
  isFirstStep = false,
  className,
  hideHeader = false,
}: StepContainerProps) {
  return (
    <div className={cn("flex w-full", className)}>
      <div
        className={cn("flex flex-col items-center w-9", isFirstStep && "pt-2")}
      >
        {/* Icon at TOP */}
        {!hideHeader && StepIconComponent && (
          <div className="py-1">
            <StepIconComponent className="size-4 stroke-text-02" />
          </div>
        )}

        {/* Connector below icon - fills remaining space */}
        {!isLastStep && <div className="w-px flex-1 bg-border-01" />}
      </div>

      <div
        className={cn(
          "w-full bg-background-tint-00",
          isLastStep && "rounded-b-12"
        )}
      >
        {!hideHeader && (
          <div className="flex items-center justify-between px-2">
            {header && (
              <Text as="p" mainUiMuted text03>
                {header}
              </Text>
            )}

            {collapsible &&
              onToggle &&
              (buttonTitle ? (
                <Button
                  tertiary
                  onClick={onToggle}
                  rightIcon={isExpanded ? SvgFold : SvgExpand}
                >
                  {buttonTitle}
                </Button>
              ) : (
                <IconButton
                  tertiary
                  onClick={onToggle}
                  icon={isExpanded ? SvgFold : SvgExpand}
                />
              ))}
          </div>
        )}

        <div className="px-2 pb-2">{children}</div>
      </div>
    </div>
  );
}

export default AgentTimeline;
