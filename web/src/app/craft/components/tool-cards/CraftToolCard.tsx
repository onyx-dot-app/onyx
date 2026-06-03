"use client";

import { useState, type ReactNode } from "react";
import { Text } from "@opal/components";
import { cn } from "@opal/utils";
import { SvgChevronDown, SvgSparkle } from "@opal/icons";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/refresh-components/Collapsible";
import CometEdge from "@/app/craft/components/CometEdge";
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
  isSkillCall,
  isSkillInvocation,
  SvgLoader,
} from "@/app/craft/components/tool-cards/helpers";
import type { ToolCallState } from "@/app/craft/types/displayTypes";

interface CraftToolCardProps {
  toolCall: ToolCallState;
  /** Initial open state. Defaults to closed (or auto-opens on failure). */
  defaultOpen?: boolean;
  /** Compact trigger padding for nested rendering inside a group. */
  dense?: boolean;
  /** Rendered inside a group — drops the failed-state border (the group has one). */
  nested?: boolean;
}

/**
 * Plain-text fallback for the card's primary content (skill, task, generic…).
 * The actual detail leads ("List Slack Channels for lookup", "Spawning
 * subagent: …") — not a bare generic verb.
 */
function primaryText(toolCall: ToolCallState): string {
  return toolCall.description || toolCall.title;
}

/**
 * A plain verb, a code-formatted chip (command, pattern, path, skill name…),
 * and an optional plain suffix ("Using <skill> skill").
 */
function verbWithCode(verb: string, code: string, suffix?: string): ReactNode {
  return (
    <>
      <Text font="main-ui-muted" color="text-04" nowrap>
        {verb}
      </Text>
      {/* 12px mono (vs the 14px sans verb): DM Mono renders visually larger
          than the sans face, so the smaller step matches their apparent size. */}
      <span className="rounded-sm bg-background-tint-01 px-1">
        <Text font="secondary-mono" color="text-04" nowrap>
          {code}
        </Text>
      </span>
      {suffix && (
        <Text font="main-ui-muted" color="text-04" nowrap>
          {suffix}
        </Text>
      )}
    </>
  );
}

/**
 * Renders the header's primary content. Bash/execute, search, and read/edit
 * lead with a verb plus the actual command / pattern / file path in a
 * code-formatted chip; everything else is plain text from `primaryText`.
 */
function renderPrimary(toolCall: ToolCallState): ReactNode {
  if (toolCall.kind === "execute" && toolCall.command) {
    return verbWithCode("Running ", toolCall.command);
  }
  if (toolCall.kind === "search" && toolCall.description) {
    return verbWithCode("Searching for ", toolCall.description);
  }
  if (toolCall.toolName === "skill" && toolCall.skillName) {
    return verbWithCode("Using ", toolCall.skillName, " skill");
  }
  if (
    (toolCall.kind === "read" || toolCall.kind === "edit") &&
    toolCall.description
  ) {
    return verbWithCode(`${toolCall.title} `, toolCall.description);
  }
  return (
    <Text font="main-ui-muted" color="text-04" nowrap>
      {primaryText(toolCall)}
    </Text>
  );
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
  // A finished skill leads with its sparkle identity (in brand blue) rather
  // than the same completion check every tool row shows — the distinguishing
  // mark for a skill card, in a group or standalone.
  if (isSkillInvocation(toolCall) && toolCall.status === "completed") {
    return (
      <SvgSparkle
        className={cn(baseClass, "stroke-status-info-05 fill-status-info-05")}
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
  nested = false,
}: CraftToolCardProps) {
  const failed = toolCall.status === "failed";
  // Failed calls are always expandable so the error is reachable, even when
  // there's no normal body content.
  const expandable = hasBodyContent(toolCall) || failed;
  const [isOpen, setIsOpen] = useState(defaultOpen ?? failed);

  // The task tool is its own clickable "Spawning subagent: …" row (no
  // collapsible body) — it navigates to the spawned subagent's transcript.
  if (toolCall.kind === "task") {
    return <TaskBody toolCall={toolCall} />;
  }

  const headerRow = (
    <div className="flex items-center gap-2 min-w-0 w-full">
      {renderStatusIcon(toolCall)}
      <span className="truncate min-w-0">{renderPrimary(toolCall)}</span>
      {/* Skill badge + chevron are pinned right so the badge aligns vertically
          across rows regardless of how long the primary text is. */}
      <span className="ml-auto flex items-center gap-2 shrink-0">
        {toolCall.skillName && toolCall.toolName !== "skill" && (
          <SkillBadge name={toolCall.skillName} />
        )}
        {/* Chevron always rendered to reserve space so the row doesn't shift. */}
        <SvgChevronDown
          aria-hidden={!expandable}
          className={cn(
            "size-4 stroke-text-03 transition-transform duration-150 shrink-0",
            !isOpen && "-rotate-90",
            !expandable && "invisible"
          )}
        />
      </span>
    </div>
  );

  const triggerClass = cn(
    "w-full text-left rounded-md",
    dense ? "px-3 py-1" : "px-3 py-2",
    expandable && "transition-colors hover:bg-background-tint-02"
  );

  // Skill work in flight gets a comet edge — the live signal. A skill
  // invocation (`toolName === "skill"`) or a tool call made inside a skill
  // (carries `skillName`) both count; a plain tool call never does.
  // Suppressed when nested in a group — the group carries the comet instead
  // (its `overflow-hidden` would clip a per-row comet).
  const isSkillInFlight =
    !nested &&
    isSkillCall(toolCall) &&
    (toolCall.status === "pending" || toolCall.status === "in_progress");

  // A standalone skill invocation keeps a thin border at rest so it stays
  // distinct from plain tool cards even after the comet stops. Grouped skill
  // rows stay borderless — the group carries the border.
  const skillCard = !nested && isSkillInvocation(toolCall);

  const card = (
    <div
      className={cn(
        "rounded-08",
        skillCard && !failed && "border-[0.5px] border-border-01",
        failed &&
          (nested
            ? "bg-status-error-00"
            : "border border-status-error-03 bg-status-error-00")
      )}
    >
      {expandable ? (
        <Collapsible open={isOpen} onOpenChange={setIsOpen}>
          <CollapsibleTrigger asChild>
            <button className={triggerClass}>{headerRow}</button>
          </CollapsibleTrigger>
          <CollapsibleContent>{renderBody(toolCall)}</CollapsibleContent>
        </Collapsible>
      ) : (
        <div className={triggerClass}>{headerRow}</div>
      )}
    </div>
  );

  if (isSkillInFlight) {
    return (
      <CometEdge active tone="info" speedSeconds={2.6}>
        {card}
      </CometEdge>
    );
  }
  return card;
}
