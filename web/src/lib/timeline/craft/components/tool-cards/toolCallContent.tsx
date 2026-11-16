"use client";

import type { ReactNode } from "react";
import { markdown } from "@opal/utils";
import type { IconFunctionComponent, RichStr } from "@opal/types";
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

/** Text that inline markdown shows as written. */
function plain(text: string): string {
  return text.replace(/[\\`*_~[\]<>#|]/g, "\\$&");
}

/** A code span that holds any text, backticks included. */
function code(text: string): string {
  const longestRun = Math.max(
    0,
    ...(text.match(/`+/g) ?? []).map((run) => run.length)
  );
  const fence = "`".repeat(longestRun + 1);
  return `${fence} ${text} ${fence}`;
}

/**
 * A plain verb, a code-formatted chip (command, pattern, path, skill name…),
 * and an optional plain suffix ("Using <skill> skill").
 */
function verbWithCode(verb: string, chip: string, suffix?: string): RichStr {
  return markdown(`${plain(verb)}${code(chip)}${suffix ? plain(suffix) : ""}`);
}

/**
 * The step header. Bash/execute, search, and read/edit lead with a verb plus
 * the actual command / pattern / file path in a code-formatted chip;
 * everything else is plain text.
 */
export function renderToolCallHeader(
  toolCall: ToolCallState
): string | RichStr {
  if (toolCall.kind === "execute" && toolCall.command) {
    if (toolCall.skillName && toolCall.description) {
      return toolCall.description;
    }
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
  return primaryText(toolCall);
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

/** The rail icon: the status while running or failed, else the kind's icon. */
export function getToolCallStepIcon(
  toolCall: ToolCallState
): IconFunctionComponent {
  if (toolCall.status === "pending" || toolCall.status === "in_progress") {
    return STEP_ICONS.running;
  }
  // A stopped call must not look finished.
  if (toolCall.status === "failed" || toolCall.status === "cancelled") {
    return STEP_ICONS.failed;
  }
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
