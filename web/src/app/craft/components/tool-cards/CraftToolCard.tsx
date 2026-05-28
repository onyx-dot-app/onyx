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
  /** Initial open state. Defaults to closed (or auto-opens on failure). */
  defaultOpen?: boolean;
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

/** Whether the per-tool body has anything worth rendering. Mirrors the
 *  early-return conditions in each body component. */
function hasBodyContent(toolCall: ToolCallState): boolean {
  if (toolCall.toolName === "websearch" || toolCall.toolName === "webfetch") {
    return !!toolCall.rawOutput;
  }
  // Write tool: no expandable body. The header already shows the file
  // path + line count ("Writing src/foo.tsx (29 lines)") — opencode's
  // raw output is just "Wrote file successfully", which adds no value.
  if (toolCall.toolName === "write") {
    return false;
  }
  switch (toolCall.kind) {
    case "execute":
      return !!(toolCall.command || toolCall.rawOutput);
    case "edit":
      return !!(toolCall.newContent || toolCall.oldContent);
    case "read":
      return !!toolCall.rawOutput;
    case "search":
      return !!toolCall.rawOutput;
    case "task":
      return !!(toolCall.command || toolCall.taskOutput || toolCall.rawOutput);
    case "other":
    default:
      return !!toolCall.rawOutput;
  }
}

function renderStatusIcon(toolCall: ToolCallState) {
  const statusDisplay = getStatusDisplay(toolCall.status);
  const baseClass = "size-4 shrink-0";
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
 * CraftToolCard - One row per tool call. Status icon + title + description
 * + chevron, with the per-tool body shown when expanded. Failed tool calls
 * auto-open so errors aren't buried.
 */
export default function CraftToolCard({
  toolCall,
  defaultOpen,
  dense = false,
}: CraftToolCardProps) {
  const failed = toolCall.status === "failed";
  const expandable = hasBodyContent(toolCall);
  const [isOpen, setIsOpen] = useState(defaultOpen ?? (failed && expandable));

  const headerRow = (
    <div className="flex items-center gap-2 min-w-0 w-full">
      {renderStatusIcon(toolCall)}
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
      {expandable && (
        <SvgChevronDown
          className={cn(
            "size-4 stroke-text-03 transition-transform duration-150 shrink-0 ml-auto",
            !isOpen && "-rotate-90"
          )}
        />
      )}
    </div>
  );

  const triggerClass = cn(
    "w-full text-left rounded-md",
    dense ? "px-3 py-1" : "px-3 py-2",
    expandable && "transition-colors hover:bg-background-tint-02"
  );

  return (
    <div
      className={cn(
        "rounded-08",
        failed && "border border-status-error-03 bg-status-error-00"
      )}
    >
      {expandable ? (
        <Collapsible open={isOpen} onOpenChange={setIsOpen}>
          <CollapsibleTrigger asChild>
            <button className={triggerClass}>{headerRow}</button>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <div className="px-3 pb-2 pt-0">{renderBody(toolCall)}</div>
          </CollapsibleContent>
        </Collapsible>
      ) : (
        <div className={triggerClass}>{headerRow}</div>
      )}
    </div>
  );
}
