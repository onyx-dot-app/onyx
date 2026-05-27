"use client";

import { useState } from "react";
import { Tag, Text } from "@opal/components";
import { cn } from "@opal/utils";
import { SvgChevronDown } from "@opal/icons";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/refresh-components/Collapsible";
import {
  TimelineRow,
  TimelineRowRailVariant,
} from "@/app/app/message/messageComponents/timeline/primitives/TimelineRow";
import { TimelineSurface } from "@/app/app/message/messageComponents/timeline/primitives/TimelineSurface";
import CraftToolCard from "@/app/craft/components/tool-cards/CraftToolCard";
import {
  getStatusDisplay,
  getToolIcon,
  SvgLoader,
} from "@/app/craft/components/tool-cards/helpers";
import type { ToolCallState } from "@/app/craft/types/displayTypes";

interface CraftToolGroupProps {
  toolCalls: ToolCallState[];
  isFirstStep?: boolean;
  isLastStep?: boolean;
  railVariant?: TimelineRowRailVariant;
}

function aggregateStatus(toolCalls: ToolCallState[]): ToolCallState["status"] {
  if (
    toolCalls.some((t) => t.status === "pending" || t.status === "in_progress")
  )
    return "in_progress";
  if (toolCalls.some((t) => t.status === "failed")) return "failed";
  if (toolCalls.some((t) => t.status === "cancelled")) return "cancelled";
  return "completed";
}

function renderRailIcon(toolCalls: ToolCallState[]) {
  const baseClass =
    "h-(--timeline-icon-size) w-(--timeline-icon-size) shrink-0";
  const aggregate = aggregateStatus(toolCalls);
  const display = getStatusDisplay(aggregate);
  if (display.showSpinner) {
    return (
      <SvgLoader
        className={cn(baseClass, "stroke-status-info-05 animate-spin")}
      />
    );
  }
  const StatusIcon = display.icon;
  if (StatusIcon) {
    return <StatusIcon className={cn(baseClass, display.iconClass)} />;
  }
  // No status icon (e.g., all "other") — fall back to the tool kind icon.
  const ToolIcon = getToolIcon(toolCalls[0]!.kind);
  return <ToolIcon className={cn(baseClass, "stroke-text-03")} />;
}

export default function CraftToolGroup({
  toolCalls,
  isFirstStep = true,
  isLastStep = true,
  railVariant = "rail",
}: CraftToolGroupProps) {
  const [isOpen, setIsOpen] = useState(false);
  const first = toolCalls[0]!;

  return (
    <TimelineRow
      railVariant={railVariant}
      icon={renderRailIcon(toolCalls)}
      showIcon={railVariant === "rail"}
      isFirst={isFirstStep}
      isLast={isLastStep}
    >
      <TimelineSurface
        className="flex flex-col"
        roundedTop={isFirstStep}
        roundedBottom={isLastStep}
      >
        <Collapsible open={isOpen} onOpenChange={setIsOpen}>
          <CollapsibleTrigger asChild>
            <button
              className={cn(
                "w-full text-left px-3 py-2 rounded-md",
                "transition-colors hover:bg-background-tint-02"
              )}
            >
              <div className="flex items-center gap-2 min-w-0 w-full">
                <Text font="main-ui-muted" color="text-04" nowrap>
                  Working
                </Text>
                <span className="ml-auto shrink-0">
                  <Tag
                    title={`${toolCalls.length} calls`}
                    size="sm"
                    color="gray"
                  />
                </span>
                <SvgChevronDown
                  className={cn(
                    "size-4 stroke-text-03 transition-transform duration-150 shrink-0",
                    !isOpen && "-rotate-90"
                  )}
                />
              </div>
            </button>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <div className="mx-2 mb-2 mt-1 rounded-md bg-background-tint-00 flex flex-col py-1">
              {toolCalls.map((toolCall) => (
                <CraftToolCard
                  key={toolCall.id}
                  toolCall={toolCall}
                  railVariant="none"
                  dense
                />
              ))}
            </div>
          </CollapsibleContent>
        </Collapsible>
      </TimelineSurface>
    </TimelineRow>
  );
}
