"use client";

import React, { FunctionComponent, useState } from "react";
import { StopReason } from "@/app/chat/services/streamingModels";
import { FullChatState } from "../interfaces";
import { TurnGroup } from "./transformers";
import { cn } from "@/lib/utils";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import { SvgFold, SvgExpand } from "@opal/icons";
import Button from "@/refresh-components/buttons/Button";
import IconButton from "@/refresh-components/buttons/IconButton";
import { IconProps } from "@opal/types";
import { TimelineRendererComponent } from "./TimelineRendererComponent";
import Text from "@/refresh-components/texts/Text";
import { useTimelineHeader } from "./useTimelineHeader";

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
}: AgentTimelineProps) {
  const [isExpanded, setIsExpanded] = useState(true);
  const handleToggle = () => setIsExpanded((prev) => !prev);
  const { headerText, hasPackets, userStopped } = useTimelineHeader(
    turnGroups,
    stopReason
  );

  if (!hasPackets && !hasDisplayContent) {
    return (
      <div className={cn("flex flex-col", className)}>
        <div className="flex w-full h-9">
          <div className="flex justify-center items-center size-9">
            <AgentAvatar agent={chatState.assistant} size={24} />
          </div>
          <div className="flex w-full h-full items-center px-2">
            <Text as="p" mainUiAction text03 className="animate-pulse">
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
            "flex w-full h-full items-center bg-background-tint-00 justify-between rounded-t-12 px-2",
            !isExpanded && "rounded-b-12"
          )}
        >
          <Text as="p" mainUiAction text03>
            {headerText}
          </Text>

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
      {isExpanded && (
        <div className="w-full">
          {turnGroups.map((turnGroup, turnIdx) =>
            turnGroup.steps.map((step, stepIdx) => (
              <TimelineRendererComponent
                key={step.key}
                packets={step.packets}
                chatState={chatState}
                onComplete={() => {}}
                animate={!stopPacketSeen}
                stopPacketSeen={stopPacketSeen}
                stopReason={stopReason}
                defaultExpanded={true}
              >
                {({ icon, status, content, isExpanded, onToggle }) => (
                  <StepContainer
                    stepIcon={icon as FunctionComponent<IconProps> | undefined}
                    header={status}
                    isExpanded={isExpanded}
                    onToggle={onToggle}
                    collapsible={true}
                    isLastStep={
                      turnIdx === turnGroups.length - 1 &&
                      stepIdx === turnGroup.steps.length - 1
                    }
                    packetLength={step.packets.length}
                  >
                    {content}
                  </StepContainer>
                )}
              </TimelineRendererComponent>
            ))
          )}
        </div>
      )}
    </div>
  );
}

export interface StepContainerProps {
  /** Main content */
  children: React.ReactNode;
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

  packetLength?: number;
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
  className,
  packetLength,
}: StepContainerProps) {
  return (
    <div className={cn("flex w-full", className)}>
      <div className="flex flex-col items-center w-9 pt-2">
        {StepIconComponent && (
          <StepIconComponent className="size-4 stroke-text-02" />
        )}
        {!isLastStep && <div className="w-px flex-1 bg-border-01" />}
      </div>

      <div
        className={cn(
          "w-full bg-background-tint-00",
          isLastStep && "rounded-b-12"
        )}
      >
        {packetLength && packetLength > 1 && (
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
