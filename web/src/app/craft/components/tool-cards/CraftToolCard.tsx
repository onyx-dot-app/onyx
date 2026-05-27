"use client";

import { useState } from "react";
import { Text } from "@opal/components";
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
import SkillBadge from "@/app/craft/components/tool-cards/SkillBadge";
import BashBody from "@/app/craft/components/tool-cards/BashBody";
import DiffBody from "@/app/craft/components/tool-cards/DiffBody";
import ReadBody from "@/app/craft/components/tool-cards/ReadBody";
import SearchBody from "@/app/craft/components/tool-cards/SearchBody";
import WebSearchBody from "@/app/craft/components/tool-cards/WebSearchBody";
import WebFetchBody from "@/app/craft/components/tool-cards/WebFetchBody";
import TaskBody from "@/app/craft/components/tool-cards/TaskBody";
import GenericBody from "@/app/craft/components/tool-cards/GenericBody";
import {
  getStatusDisplay,
  getToolIcon,
  SvgLoader,
} from "@/app/craft/components/tool-cards/helpers";
import type { ToolCallState } from "@/app/craft/types/displayTypes";

interface CraftToolCardProps {
  toolCall: ToolCallState;
  /** Initial open state. Defaults to closed. */
  defaultOpen?: boolean;
  /** First card in a contiguous rail series — controls top connector. */
  isFirstStep?: boolean;
  /** Last card in a contiguous rail series — controls bottom connector. */
  isLastStep?: boolean;
  /**
   * Left-column variant. "rail" shows status icon + connector (top-level use),
   * "spacer" reserves the column width without rail (nested use under a parent
   * rail), "none" omits the column entirely.
   */
  railVariant?: TimelineRowRailVariant;
  /** Compact trigger padding for nested rendering inside a group. */
  dense?: boolean;
}

function renderBody(toolCall: ToolCallState) {
  if (toolCall.toolName === "websearch") {
    return <WebSearchBody toolCall={toolCall} />;
  }
  if (toolCall.toolName === "webfetch") {
    return <WebFetchBody toolCall={toolCall} />;
  }

  switch (toolCall.kind) {
    case "execute":
      return <BashBody toolCall={toolCall} />;
    case "edit":
      return <DiffBody toolCall={toolCall} />;
    case "read":
      return <ReadBody toolCall={toolCall} />;
    case "search":
      return <SearchBody toolCall={toolCall} />;
    case "task":
      return <TaskBody toolCall={toolCall} />;
    case "other":
    default:
      return <GenericBody toolCall={toolCall} />;
  }
}

function renderRailIcon(toolCall: ToolCallState) {
  const statusDisplay = getStatusDisplay(toolCall.status);
  const baseClass =
    "h-(--timeline-icon-size) w-(--timeline-icon-size) shrink-0";
  if (statusDisplay.showSpinner) {
    return (
      <SvgLoader
        className={cn(baseClass, "stroke-status-info-05 animate-spin")}
      />
    );
  }
  const StatusIcon = statusDisplay.icon;
  if (StatusIcon) {
    return <StatusIcon className={cn(baseClass, statusDisplay.iconClass)} />;
  }
  const ToolIcon = getToolIcon(toolCall.kind);
  return <ToolIcon className={cn(baseClass, "stroke-text-03")} />;
}

/**
 * CraftToolCard - The single entry point for rendering a tool call in the
 * Craft transcript. Composes the /app timeline primitives (TimelineRow +
 * TimelineSurface) so Craft and the main chat share rail/connector identity,
 * and slots in per-tool body components for the expanded view.
 */
export default function CraftToolCard({
  toolCall,
  defaultOpen,
  isFirstStep = true,
  isLastStep = true,
  railVariant = "rail",
  dense = false,
}: CraftToolCardProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen ?? false);

  return (
    <TimelineRow
      railVariant={railVariant}
      icon={renderRailIcon(toolCall)}
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
                "w-full text-left rounded-md",
                dense ? "px-3 py-1" : "px-3 py-2",
                "transition-colors hover:bg-background-tint-02"
              )}
            >
              <div className="flex items-center gap-2 min-w-0 w-full">
                <Text font="main-ui-muted" color="text-04" nowrap>
                  {toolCall.title}
                </Text>
                {toolCall.description && (
                  <span className="truncate min-w-0">
                    <Text font="main-ui-body" color="text-03" nowrap>
                      {toolCall.description}
                    </Text>
                  </span>
                )}
                {toolCall.skillName && <SkillBadge name={toolCall.skillName} />}
                <SvgChevronDown
                  className={cn(
                    "size-4 stroke-text-03 transition-transform duration-150 shrink-0 ml-auto",
                    !isOpen && "-rotate-90"
                  )}
                />
              </div>
            </button>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <div className="px-3 pb-2 pt-0">{renderBody(toolCall)}</div>
          </CollapsibleContent>
        </Collapsible>
      </TimelineSurface>
    </TimelineRow>
  );
}
