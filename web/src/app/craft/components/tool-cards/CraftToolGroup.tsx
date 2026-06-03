"use client";

import { useEffect, useRef, useState } from "react";
import { Tag, Text } from "@opal/components";
import { cn } from "@opal/utils";
import { SvgCheckAll, SvgChevronDown } from "@opal/icons";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/refresh-components/Collapsible";
import CraftToolCard from "@/app/craft/components/tool-cards/CraftToolCard";
import CometEdge from "@/app/craft/components/CometEdge";
import {
  isSkillCall,
  SvgLoader,
} from "@/app/craft/components/tool-cards/helpers";
import type { ToolCallState } from "@/app/craft/types/displayTypes";

interface CraftToolGroupProps {
  toolCalls: ToolCallState[];
  /** Once an assistant message follows, animate the block closed. */
  autoCollapse?: boolean;
  /** Override the initial open/closed state (useful in Storybook). */
  defaultOpen?: boolean;
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

function renderStatusIcon(toolCalls: ToolCallState[]) {
  const baseClass = "size-4 shrink-0";
  const aggregate = aggregateStatus(toolCalls);
  if (aggregate === "in_progress") {
    return (
      <SvgLoader
        className={cn(baseClass, "stroke-status-info-05 animate-spin")}
      />
    );
  }
  return <SvgCheckAll className={cn(baseClass, "stroke-text-03")} />;
}

export default function CraftToolGroup({
  toolCalls,
  autoCollapse = false,
  defaultOpen,
}: CraftToolGroupProps) {
  const aggregate = aggregateStatus(toolCalls);
  // Open while the run is active so streaming calls stay visible and nothing
  // collapses as new calls append; settled groups start collapsed.
  const [isOpen, setIsOpen] = useState(
    defaultOpen ?? aggregate === "in_progress"
  );
  const failedCount = toolCalls.filter((t) => t.status === "failed").length;
  // Skill groups get a comet while running and a thin border at rest.
  const skillGroup = toolCalls.some(isSkillCall);
  const skillActive = aggregate === "in_progress" && skillGroup;

  // Fold closed once a message follows; fire once so a manual re-open sticks.
  const didAutoCollapse = useRef(false);
  useEffect(() => {
    if (autoCollapse && !didAutoCollapse.current) {
      didAutoCollapse.current = true;
      setIsOpen(false);
    }
  }, [autoCollapse]);

  return (
    <CometEdge active={skillActive} tone="info" speedSeconds={2.6}>
      <div
        className={cn(
          "rounded-08 overflow-hidden",
          skillGroup && "border-[0.5px] border-border-01"
        )}
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
                {renderStatusIcon(toolCalls)}
                <Text font="main-ui-muted" color="text-04" nowrap>
                  Working
                </Text>
                <span className="ml-auto shrink-0 flex items-center gap-2">
                  {failedCount > 0 && (
                    <Tag
                      title={`${failedCount} failed`}
                      size="sm"
                      color="red"
                    />
                  )}
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
            <div className="flex flex-col border-t-[0.5px] border-border-01">
              {toolCalls.map((toolCall) => (
                <CraftToolCard key={toolCall.id} toolCall={toolCall} nested />
              ))}
            </div>
          </CollapsibleContent>
        </Collapsible>
      </div>
    </CometEdge>
  );
}
