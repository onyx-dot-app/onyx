"use client";

import type { ReactNode } from "react";
import { Text } from "@opal/components";
import type { IconFunctionComponent } from "@opal/types";
import { STEP_ICONS } from "@/lib/timeline/icons";
import BashBody from "@/lib/timeline/craft/components/tool-cards/BashBody";
import DiffBody from "@/lib/timeline/craft/components/tool-cards/DiffBody";
import ReadBody from "@/lib/timeline/craft/components/tool-cards/ReadBody";
import SearchBody from "@/lib/timeline/craft/components/tool-cards/SearchBody";
import WebSearchBody from "@/lib/timeline/craft/components/tool-cards/WebSearchBody";
import WebFetchBody from "@/lib/timeline/craft/components/tool-cards/WebFetchBody";
import GenericBody from "@/lib/timeline/craft/components/tool-cards/GenericBody";
import { isSkillInvocation } from "@/lib/timeline/craft/components/tool-cards/helpers";
import type { ToolCallState } from "@/app/craft/types/displayTypes";

/**
 * Plain-text fallback for the step's primary content (skill, task, generic…).
 * The actual detail leads ("List Slack Channels for lookup", "Spawning
 * subagent: …") — not a bare generic verb.
 */
function primaryText(toolCall: ToolCallState): string {
  return toolCall.description || toolCall.title;
}

export interface ToolCallHeader {
  /** The short title, in the log line's title column. */
  title: string;
  /** What the call acted on (a command, a pattern, a path), as a code chip. */
  detail?: ReactNode;
}

/** A code-formatted chip for the detail column. */
function codeChip(text: string): ReactNode {
  return (
    <span className="min-w-0 rounded-sm bg-background-tint-01 px-1">
      <Text font="secondary-mono" color="text-03" maxLines={1}>
        {text}
      </Text>
    </span>
  );
}

/**
 * The step's title and detail. Bash/execute, search, skills and read/edit get
 * a verb as the title and the actual command, pattern, skill or file path as a
 * code chip; everything else is plain text.
 */
export function renderToolCallHeader(toolCall: ToolCallState): ToolCallHeader {
  if (toolCall.kind === "execute" && toolCall.command) {
    if (toolCall.skillName && toolCall.description) {
      return { title: toolCall.description };
    }
    return { title: "Running", detail: codeChip(toolCall.command) };
  }
  if (toolCall.kind === "search" && toolCall.description) {
    return { title: "Searching for", detail: codeChip(toolCall.description) };
  }
  if (toolCall.toolName === "skill" && toolCall.skillName) {
    return { title: "Using skill", detail: codeChip(toolCall.skillName) };
  }
  if (
    (toolCall.kind === "read" || toolCall.kind === "edit") &&
    toolCall.description
  ) {
    return { title: toolCall.title, detail: codeChip(toolCall.description) };
  }
  return { title: primaryText(toolCall) };
}

export function renderToolCallBody(toolCall: ToolCallState): ReactNode {
  if (failedFileCallError(toolCall)) {
    return <GenericBody toolCall={toolCall} />;
  }
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

/** A failed edit or write call shows its error, not the attempted diff. */
function failedFileCallError(toolCall: ToolCallState): boolean {
  return (
    toolCall.status === "failed" &&
    (toolCall.kind === "edit" || toolCall.toolName === "write") &&
    !!toolCall.rawOutput
  );
}

/** Whether the per-tool body has anything worth rendering. Mirrors the
 *  early-return conditions in each body component. */
export function hasToolCallBody(toolCall: ToolCallState): boolean {
  if (failedFileCallError(toolCall)) return true;
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

/** The step kind's icon; `RunStep` shows the status while running or failed. */
export function getToolCallIcon(
  toolCall: ToolCallState
): IconFunctionComponent {
  if (isSkillInvocation(toolCall)) return STEP_ICONS.skill;
  if (toolCall.toolName === "websearch") return STEP_ICONS.webSearch;
  if (toolCall.toolName === "webfetch") return STEP_ICONS.fetch;
  switch (toolCall.kind) {
    case "execute":
      return STEP_ICONS.execute;
    case "read":
      return STEP_ICONS.read;
    case "edit":
      return STEP_ICONS.edit;
    case "search":
      return STEP_ICONS.search;
    case "task":
      return STEP_ICONS.agent;
    case "other":
    default:
      return STEP_ICONS.tool;
  }
}
