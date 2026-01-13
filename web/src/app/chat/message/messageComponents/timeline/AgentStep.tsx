"use client";

import React, { useState, useCallback } from "react";
import { cn } from "@/lib/utils";

export type IconType = "default" | "loading" | "complete" | "error";

export interface AgentStepProps {
  /** Icon element to display on the left */
  icon: React.ReactNode;
  /** Icon state - affects visual styling */
  iconType?: IconType;
  /** Optional header content (any component) */
  header?: React.ReactNode;
  /** Optional right-aligned actions */
  rightActions?: React.ReactNode;
  /** Main content of the step */
  children: React.ReactNode;
  /** Disable hover effect on container (icon can still hover) */
  hoverDisabled?: boolean;
  /** Show connector line to next step */
  showConnector?: boolean;
  /** Additional class names for the container */
  className?: string;
  /** Test ID for e2e testing */
  "data-testid"?: string;
}

/**
 * AgentStep - Atomic container for timeline steps
 *
 * Structure:
 * ┌──────────────────────────────────────────────────────┐
 * │ [Icon]  │  [Header]                  [RightActions]  │
 * │   │     │                                            │
 * │   │     │  [Children]                                │
 * │   ┆     │                                            │  ← connector
 * └──────────────────────────────────────────────────────┘
 *
 * Features:
 * - Synchronized hover between icon and container
 * - Optional connector line to next step
 * - Supports nesting for sub-steps (e.g., research agent)
 */
export function AgentStep({
  icon,
  iconType = "default",
  header,
  rightActions,
  children,
  hoverDisabled = false,
  showConnector = false,
  className,
  "data-testid": testId,
}: AgentStepProps) {
  const [isHovered, setIsHovered] = useState(false);

  const handleMouseEnter = useCallback(() => {
    setIsHovered(true);
  }, []);

  const handleMouseLeave = useCallback(() => {
    setIsHovered(false);
  }, []);

  return (
    <div
      className={cn("flex gap-3", className)}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      data-testid={testId}
    >
      {/* Icon column with optional connector */}
      <div className="flex flex-col items-center">
        <StepIcon
          icon={icon}
          iconType={iconType}
          isHovered={isHovered && !hoverDisabled}
        />
        {showConnector && <StepConnector />}
      </div>

      {/* Content column */}
      <StepContainer
        header={header}
        rightActions={rightActions}
        isHovered={isHovered && !hoverDisabled}
      >
        {children}
      </StepContainer>
    </div>
  );
}

interface StepIconProps {
  icon: React.ReactNode;
  iconType: IconType;
  isHovered: boolean;
}

function StepIcon({ icon, iconType, isHovered }: StepIconProps) {
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
        isHovered && iconType !== "error" && "text-text-04"
      )}
    >
      {icon}
    </div>
  );
}

function StepConnector() {
  return (
    <div className="w-px flex-1 min-h-4 bg-border-01 my-1" aria-hidden="true" />
  );
}

interface StepContainerProps {
  header?: React.ReactNode;
  rightActions?: React.ReactNode;
  children: React.ReactNode;
  isHovered: boolean;
}

function StepContainer({
  header,
  rightActions,
  children,
  isHovered,
}: StepContainerProps) {
  return (
    <div
      className={cn(
        "flex-1 min-w-0 rounded-lg transition-colors duration-150 pb-3",
        isHovered && "bg-background-tint-01"
      )}
    >
      {/* Header row */}
      {(header || rightActions) && (
        <div className="flex items-center justify-between gap-2 mb-1">
          <div className="flex-1 min-w-0">{header}</div>
          {rightActions && <div className="flex-shrink-0">{rightActions}</div>}
        </div>
      )}

      {/* Main content */}
      <div className="min-w-0">{children}</div>
    </div>
  );
}

export default AgentStep;
