"use client";

import React, { useMemo, useState } from "react";
import { StopReason } from "@/app/chat/services/streamingModels";
import { GroupedPacket } from "../packetProcessor";
import { FullChatState } from "../interfaces";
import {
  transformPacketGroups,
  groupStepsByTurn,
  TurnGroup,
  TransformedStep,
} from "./transformers";
import { cn } from "@/lib/utils";
import { IconType } from "./AgentStep";
import { StepContent } from "./StepContent";
import { ParallelSteps } from "./ParallelSteps";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import { SvgFold, SvgExpand } from "@opal/icons";
import Button from "@/refresh-components/buttons/Button";
import IconButton from "@/refresh-components/buttons/IconButton";

export interface AgentTimelineProps {
  /** Grouped packets from usePacketProcessor */
  packetGroups: GroupedPacket[];
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
  /** Additional class names */
  className?: string;
  /** Test ID for e2e testing */
  "data-testid"?: string;
}

/**
 * AgentTimeline - Self-contained timeline component
 *
 * Renders the complete two-column layout:
 * - Left column: Avatar + step icons with connectors
 * - Right column: Step content containers + children slot
 *
 * Usage:
 * ```tsx
 * <AgentTimeline
 *   packetGroups={toolGroups}
 *   chatState={effectiveChatState}
 *   stopPacketSeen={stopPacketSeen}
 *   finalAnswerComing={finalAnswerComing}
 *   hasDisplayContent={displayGroups.length > 0}
 * >
 *   {/* Final message content + MessageToolbar *\/}
 * </AgentTimeline>
 * ```
 */
export function AgentTimeline({
  packetGroups,
  chatState,
  stopPacketSeen = false,
  stopReason,
  finalAnswerComing = false,
  hasDisplayContent = false,
  children,
  className,
  "data-testid": testId,
}: AgentTimelineProps) {
  // Transform packets into step data
  const allSteps = useMemo(
    () => transformPacketGroups(packetGroups),
    [packetGroups]
  );

  // Group steps by turn for parallel detection
  const turnGroups = useMemo(() => groupStepsByTurn(allSteps), [allSteps]);
  const hasSteps = turnGroups.length > 0;

  return (
    <div className={cn("flex items-start", className)} data-testid={testId}>
      {/* Left column: Avatar + Step icons */}
      <div className="flex flex-col items-center flex-shrink-0">
        <AgentAvatar agent={chatState.assistant} size={24} />
        {/* Connector from avatar to first step */}
        {hasSteps && <StepConnector className="min-h-3" />}
        {/* Step icons */}
        {turnGroups.map((turnGroup, turnIndex) => {
          const firstStep = getFirstStep(turnGroup);
          if (!firstStep) return null;
          const showConnector = shouldShowConnector(
            turnIndex,
            turnGroups.length,
            hasDisplayContent && finalAnswerComing
          );
          return (
            <React.Fragment key={`icon-${turnGroup.turnIndex}`}>
              <StepIcon icon={firstStep.icon} iconType={firstStep.iconType} />
              {showConnector && <StepConnector />}
            </React.Fragment>
          );
        })}
      </div>

      {/* Right column: Content */}
      <div className="max-w-message-max break-words pl-4 w-full">
        {/* Tool steps */}
        {hasSteps && (
          <div className="mb-4">
            {turnGroups.map((turnGroup) => {
              const firstStep = getFirstStep(turnGroup);
              if (!firstStep) return null;

              if (turnGroup.isParallel) {
                // Multiple steps in same turn - render as tabs
                return (
                  <StepContainer key={`content-${turnGroup.turnIndex}`}>
                    <ParallelSteps
                      turnGroup={turnGroup}
                      chatState={chatState}
                      stopPacketSeen={stopPacketSeen}
                    />
                  </StepContainer>
                );
              }

              // Single steps in turn - render each
              return turnGroup.steps.map((step) => (
                <StepContainer key={step.key}>
                  <StepContent
                    packets={step.packets}
                    chatState={chatState}
                    isLoading={step.iconType === "loading"}
                    stopPacketSeen={stopPacketSeen}
                    stopReason={stopReason}
                  >
                    {({ content }) => <>{content}</>}
                  </StepContent>
                </StepContainer>
              ));
            })}
          </div>
        )}

        {/* Slot for final message content + MessageToolbar */}
        {children}
      </div>
    </div>
  );
}

/**
 * StepIcon - Standalone icon component for timeline steps
 */
export interface StepIconProps {
  /** Icon element to display */
  icon: React.ReactNode;
  /** Icon state - affects visual styling */
  iconType?: IconType;
  /** Whether parent is hovered */
  isHovered?: boolean;
  /** Additional class names */
  className?: string;
}

export function StepIcon({
  icon,
  iconType = "default",
  isHovered = false,
  className,
}: StepIconProps) {
  return (
    <div
      className={cn(
        "flex items-center justify-center w-6 h-6 rounded-full transition-colors duration-150",
        // Default state
        iconType === "default" && "text-text-03",
        // Loading state - show animation
        iconType === "loading" && "text-text-03 animate-pulse",
        // Complete state
        iconType === "complete" && "text-text-04",
        // Error state
        iconType === "error" && "text-red-500",
        // Hover state - darken text color, NO background
        isHovered && iconType !== "error" && "text-text-04",
        className
      )}
    >
      {icon}
    </div>
  );
}

/**
 * StepConnector - Vertical connector line between steps
 */
export interface StepConnectorProps {
  /** Additional class names */
  className?: string;
}

export function StepConnector({ className }: StepConnectorProps) {
  return (
    <div
      className={cn("w-px flex-1 min-h-4 bg-border-01 my-1", className)}
      aria-hidden="true"
    />
  );
}

/**
 * StepContainer - Content container with header and optional collapsible
 */
export interface StepContainerProps {
  /** Main content */
  children: React.ReactNode;
  /** Header left slot - accepts any component */
  header?: React.ReactNode;
  /** Time/duration string to display (e.g., "2.3s") */
  duration?: string;
  /** Whether collapsible control is shown */
  collapsible?: boolean;
  /** Initial expanded state (default: true) */
  defaultExpanded?: boolean;
  /** Whether container is hovered */
  isHovered?: boolean;
  /** Additional class names */
  className?: string;
}

export function StepContainer({
  children,
  header,
  duration,
  collapsible = true,
  defaultExpanded = true,
  isHovered = false,
  className,
}: StepContainerProps) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);
  const handleToggle = () => setIsExpanded((prev) => !prev);
  const showHeader = header || duration || collapsible;

  return (
    <div
      className={cn(
        "flex-1 min-w-0 rounded-12 transition-colors duration-150 bg-background-tint-00 p-1",
        isHovered && "bg-background-tint-01",
        className
      )}
    >
      {showHeader && (
        <div className="flex items-center justify-between">
          {/* Left section */}
          <div className="flex-1 min-w-0 p-1">{header}</div>

          {/* Right section: Collapsible button with duration */}
          <div className="flex items-center gap-2 flex-shrink-0">
            {collapsible &&
              (duration ? (
                <Button
                  tertiary
                  onClick={handleToggle}
                  rightIcon={isExpanded ? SvgFold : SvgExpand}
                  aria-expanded={isExpanded}
                  aria-label={isExpanded ? "Collapse" : "Expand"}
                >
                  {duration}
                </Button>
              ) : (
                <IconButton
                  tertiary
                  onClick={handleToggle}
                  icon={isExpanded ? SvgFold : SvgExpand}
                  aria-expanded={isExpanded}
                  aria-label={isExpanded ? "Collapse" : "Expand"}
                />
              ))}
          </div>
        </div>
      )}

      {/* Collapsible content */}
      {collapsible ? isExpanded && children : children}
    </div>
  );
}

/**
 * Helper to get the first step from a turn group (for icon display)
 */
export function getFirstStep(turnGroup: TurnGroup): TransformedStep | null {
  return turnGroup.steps[0] ?? null;
}

/**
 * Helper to determine if connector should show after a turn group
 */
export function shouldShowConnector(
  turnIndex: number,
  totalTurns: number,
  hasMoreContent?: boolean
): boolean {
  const isLastTurn = turnIndex === totalTurns - 1;
  return !isLastTurn || !!hasMoreContent;
}

export default AgentTimeline;
