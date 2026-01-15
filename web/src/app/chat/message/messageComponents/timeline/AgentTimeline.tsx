"use client";

import React, { FunctionComponent, useMemo, useState } from "react";
import { StopReason } from "@/app/chat/services/streamingModels";
import { GroupedPacket } from "../packetProcessor";
import { FullChatState } from "../interfaces";
import { TurnGroup, TransformedStep } from "./transformers";
import { cn } from "@/lib/utils";
import { IconType } from "./AgentStep";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import { SvgFold, SvgExpand } from "@opal/icons";
import Button from "@/refresh-components/buttons/Button";
import IconButton from "@/refresh-components/buttons/IconButton";
import { IconProps } from "@opal/types";
import { RendererComponent } from "../renderMessageComponent";
import Text from "@/refresh-components/texts/Text";

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
  collapsible = true,
  buttonTitle,
  className,
  "data-testid": testId,
}: AgentTimelineProps) {
  const [isExpanded, setIsExpanded] = useState(true);
  const handleToggle = () => setIsExpanded((prev) => !prev);

  if (packetGroups.length === 0) {
    return (
      <Text as="p" mainUiAction text05 className="animate-pulse">
        Thinking...
      </Text>
    );
  }

  return (
    <div className={cn("flex flex-col", className)}>
      <div className="flex w-full h-9">
        <div className="flex justify-center items-center size-9">
          <AgentAvatar agent={chatState.assistant} size={24} />
        </div>
        {/* Header row */}
        <div
          className={cn(
            "flex w-full h-full items-center bg-background-tint-00 justify-between rounded-t-12",
            !isExpanded && "rounded-b-12"
          )}
        >
          <Text as="p" mainUiAction text05>
            Thinking...
          </Text>

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
      </div>
      {/* Children (collapsible) */}
      {isExpanded && (
        <div className="w-full">
          {packetGroups.map((group) => (
            <RendererComponent
              key={`${group.turn_index}-${group.tab_index}`}
              packets={group.packets}
              chatState={chatState}
              onComplete={() => {}}
              animate={!stopPacketSeen}
              stopPacketSeen={stopPacketSeen}
              stopReason={stopReason}
            >
              {({ icon, status, content }) => (
                <StepContainer
                  stepIcon={icon as FunctionComponent<IconProps> | undefined}
                  header={status}
                  collapsible={true}
                  defaultExpanded={true}
                  isLastStep={group.turn_index === packetGroups.length - 1}
                >
                  {content}
                </StepContainer>
              )}
            </RendererComponent>
          ))}
        </div>
      )}
    </div>
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
  /** Whether this is the last step */
  isLastStep?: boolean;

  packetLength?: number;
}

export function StepContainer({
  children,
  stepIcon: StepIconComponent,
  header,
  buttonTitle,
  collapsible = true,
  defaultExpanded = true,
  isLastStep = false,
  className,
  packetLength,
}: StepContainerProps) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);
  const handleToggle = () => setIsExpanded((prev) => !prev);

  return (
    <div className={cn("flex w-full", className)}>
      <div className="flex justify-center w-9 border-t">
        {StepIconComponent && (
          <StepIconComponent className="size-4 stroke-text-02" />
        )}
        {isExpanded && !isLastStep && (
          <div className="w-px flex-1 bg-border-01" />
        )}
      </div>

      {/* Right column: Content box (with bg + rounded) */}
      <div
        className={cn(
          "w-full bg-background-tint-00",
          isLastStep && "rounded-b-12"
        )}
      >
        {/* Header row */}
        {packetLength && packetLength > 1 && (
          <div className="flex items-center justify-between">
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
