"use client";

import React from "react";
import { TurnGroup } from "./transformers";
import { StepIcon, StepConnector, getFirstStep } from "./AgentTimeline";
import { cn } from "@/lib/utils";

export interface TimelineIconsProps {
  /** Turn groups containing step data */
  turnGroups: TurnGroup[];
  /** Whether to show connector after the last step (to connect to content below) */
  showFinalConnector?: boolean;
  /** Additional class names */
  className?: string;
}

/**
 * Renders the icon column for the timeline.
 * Shows step icons with vertical connectors between them.
 */
export function TimelineIcons({
  turnGroups,
  showFinalConnector = false,
  className,
}: TimelineIconsProps) {
  if (turnGroups.length === 0) return null;

  return (
    <div className={cn("flex flex-col items-center", className)}>
      {turnGroups.map((turnGroup, turnIndex) => {
        const firstStep = getFirstStep(turnGroup);
        if (!firstStep) return null;

        const isLastTurn = turnIndex === turnGroups.length - 1;
        const showConnector = !isLastTurn || showFinalConnector;

        return (
          <React.Fragment key={`icon-${turnGroup.turnIndex}`}>
            <StepIcon icon={firstStep.icon} iconType={firstStep.iconType} />
            {showConnector && <StepConnector />}
          </React.Fragment>
        );
      })}
    </div>
  );
}
