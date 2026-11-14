"use client";

import type { ReactNode } from "react";
import { Text } from "@opal/components";
import { cn } from "@opal/utils";
import {
  SvgAlertCircle,
  SvgEdit,
  SvgGlobe,
  SvgLoader,
  SvgSparkle,
} from "@opal/icons";
import type { IconFunctionComponent, IconProps } from "@opal/types";
import BashBody from "@/lib/timeline/craft/components/tool-cards/BashBody";
import DiffBody from "@/lib/timeline/craft/components/tool-cards/DiffBody";
import ReadBody from "@/lib/timeline/craft/components/tool-cards/ReadBody";
import SearchBody from "@/lib/timeline/craft/components/tool-cards/SearchBody";
import WebSearchBody from "@/lib/timeline/craft/components/tool-cards/WebSearchBody";
import WebFetchBody from "@/lib/timeline/craft/components/tool-cards/WebFetchBody";
import GenericBody from "@/lib/timeline/craft/components/tool-cards/GenericBody";
import {
  getToolIcon,
  isSkillInvocation,
} from "@/lib/timeline/craft/components/tool-cards/helpers";
import type { ToolCallState } from "@/app/craft/types/displayTypes";

/**
 * Plain-text fallback for the step's primary content (skill, task, generic…).
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
      <Text font="main-ui-muted" color="text-04" wordWrap="whitespace-nowrap">
        {verb}
      </Text>
      {/* 12px mono (vs the 14px sans verb): DM Mono renders visually larger
          than the sans face, so the smaller step matches their apparent size. */}
      <span className="rounded-sm bg-background-tint-01 px-1">
        <Text
          font="secondary-mono"
          color="text-04"
          wordWrap="whitespace-nowrap"
        >
          {code}
        </Text>
      </span>
      {suffix && (
        <Text font="main-ui-muted" color="text-04" wordWrap="whitespace-nowrap">
          {suffix}
        </Text>
      )}
    </>
  );
}

/**
 * The step header. Bash/execute, search, and read/edit lead with a verb plus
 * the actual command / pattern / file path in a code-formatted chip;
 * everything else is plain text.
 */
export function renderToolCallHeader(toolCall: ToolCallState): ReactNode {
  if (toolCall.kind === "execute" && toolCall.command) {
    if (toolCall.skillName && toolCall.description) {
      return (
        <Text font="main-ui-muted" color="text-04" wordWrap="whitespace-nowrap">
          {toolCall.description}
        </Text>
      );
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
  return (
    <Text font="main-ui-muted" color="text-04" wordWrap="whitespace-nowrap">
      {primaryText(toolCall)}
    </Text>
  );
}

export function renderToolCallBody(toolCall: ToolCallState): ReactNode {
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
export function hasToolCallBody(toolCall: ToolCallState): boolean {
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

function SpinningLoader({ className, ...props }: IconProps) {
  return <SvgLoader {...props} className={cn(className, "animate-spin")} />;
}

/** The rail icon: a spinner while running, otherwise the tool's own icon. */
export function getToolCallStepIcon(
  toolCall: ToolCallState
): IconFunctionComponent {
  if (toolCall.status === "pending" || toolCall.status === "in_progress") {
    return SpinningLoader;
  }
  // A stopped call must not look finished.
  if (toolCall.status === "failed" || toolCall.status === "cancelled") {
    return SvgAlertCircle;
  }
  // A finished skill leads with its sparkle.
  if (isSkillInvocation(toolCall) && toolCall.status === "completed") {
    return SvgSparkle;
  }
  // Chat's icons for the same steps.
  if (toolCall.toolName === "websearch") return SvgGlobe;
  if (toolCall.toolName === "webfetch") return SvgEdit;
  return getToolIcon(toolCall.kind);
}
