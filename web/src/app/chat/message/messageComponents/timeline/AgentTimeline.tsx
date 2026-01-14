"use client";

import React, { FunctionComponent, useMemo, useState } from "react";
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
import { IconProps } from "@opal/types";

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
  /** Header to render above the timeline */
  header?: React.ReactNode;
  /** Whether the timeline is collapsible */
  collapsible?: boolean;
  /** Title of the button to toggle the timeline */
  buttonTitle?: string;
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
  header,
  collapsible,
  buttonTitle,
  children,
  className,
  "data-testid": testId,
}: AgentTimelineProps) {
  const [isExpanded, setIsExpanded] = useState(true);
  const handleToggle = () => setIsExpanded((prev) => !prev);

  return (
    <div className={cn("flex", className)}>
      {/* Left column: Icon */}
      <div className="flex flex-col items-center flex-shrink-0 size-9">
        <AgentAvatar agent={chatState.assistant} size={24} />
      </div>

      {/* Right column: Content box (with bg + rounded) */}
      <div className="flex-1 overflow-hidden bg-background-tint-00 rounded-12">
        {/* Header row */}
        <div className="flex items-center justify-between p-2">
          {/* Header text */}
          {header && <div className="text-text-03">{header}</div>}

          {/* Button */}
          {collapsible &&
            (buttonTitle ? (
              <Button
                tertiary
                onClick={handleToggle}
                rightIcon={isExpanded ? SvgFold : SvgExpand}
              >
                {buttonTitle}
              </Button>
            ) : (
              <IconButton
                tertiary
                onClick={handleToggle}
                icon={isExpanded ? SvgFold : SvgExpand}
              />
            ))}
        </div>

        {/* Children (collapsible) */}
        {isExpanded && <div className="px-2 pb-2">{children}</div>}
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
 *
 * Layout:
 * - ROW 1: Icon + Header + Button (same row, space-between)
 * - ROW 2: Connector column + Children column (two columns)
 */
export interface StepContainerProps {
  /** Main content */
  children: React.ReactNode;
  /** Step icon component */
  stepIcon?: FunctionComponent<IconProps>;
  /** Header left slot - accepts any component */
  header?: React.ReactNode;
  /** Time/duration string to display (e.g., "2.3s") */
  buttonTitle?: string;
  /** Whether collapsible control is shown */
  collapsible?: boolean;
  /** Initial expanded state (default: true) */
  defaultExpanded?: boolean;
  /** Additional class names */
  className?: string;
}

export function StepContainer({
  children,
  stepIcon: StepIconComponent,
  header,
  buttonTitle,
  collapsible = true,
  defaultExpanded = true,
  className,
}: StepContainerProps) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);
  const handleToggle = () => setIsExpanded((prev) => !prev);

  const showHeader = header || buttonTitle || StepIconComponent || collapsible;

  return (
    <div className={cn("flex", className)}>
      {/* Left column: Icon + Connector (no styling) */}
      <div className="flex flex-col items-center flex-shrink-0 w-9">
        {/* Icon */}
        {StepIconComponent && (
          <div className="flex items-center justify-center h-9">
            <StepIconComponent size={24} />
          </div>
        )}
        {/* Connector */}
        {isExpanded && <div className="w-px flex-1 bg-border-01" />}
      </div>

      {/* Right column: Content box (with bg + rounded) */}
      <div className={cn("flex-1 overflow-hidden", "bg-background-tint-00")}>
        {/* Header row */}
        {showHeader && (
          <div className="flex items-center justify-between p-2">
            {/* Header text */}
            {header && <div className="text-text-03">{header}</div>}

            {/* Button */}
            {collapsible &&
              (buttonTitle ? (
                <Button
                  tertiary
                  onClick={handleToggle}
                  rightIcon={isExpanded ? SvgFold : SvgExpand}
                >
                  {buttonTitle}
                </Button>
              ) : (
                <IconButton
                  tertiary
                  onClick={handleToggle}
                  icon={isExpanded ? SvgFold : SvgExpand}
                />
              ))}
          </div>
        )}

        {/* Children (collapsible) */}
        {isExpanded && <div className="px-2 pb-2">{children}</div>}
      </div>
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
