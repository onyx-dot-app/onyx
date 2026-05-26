"use client";

import { cn } from "@opal/utils";
import { Text, Tag } from "@opal/components";
import { SvgBubbleText } from "@opal/icons";
import type { ToolCardBodyProps } from "@/app/craft/components/tool-cards/interfaces";

/**
 * TaskBody - Renderer for the task (subagent) tool.
 *
 * Shows the subagent type badge, the prompt sent to the subagent, and the
 * final output when the task has completed. Replaces the previous behavior
 * of dumping the subagent output as a stray text item in the parent
 * transcript.
 */
export default function TaskBody({ toolCall }: ToolCardBodyProps) {
  const subagentType = toolCall.subagentType;
  const prompt = toolCall.command || toolCall.rawOutput;
  const output = toolCall.taskOutput;

  return (
    <div className="flex flex-col gap-2">
      {subagentType && (
        <div className="flex items-center gap-2">
          <Tag icon={SvgBubbleText} title={subagentType} color="purple" />
          <Text font="main-ui-muted" color="text-02">
            subagent
          </Text>
        </div>
      )}

      {prompt && (
        <div
          className={cn(
            "rounded-08 border-[0.5px] bg-background-neutral-01 border-border-01",
            "p-3 overflow-auto max-h-[14rem] whitespace-pre-wrap wrap-break-word"
          )}
        >
          <Text font="main-ui-muted" color="text-02">
            Prompt
          </Text>
          <div className="mt-1">
            <Text as="p" font="secondary-body" color="text-04">
              {prompt}
            </Text>
          </div>
        </div>
      )}

      {output && (
        <div
          className={cn(
            "rounded-08 border-[0.5px] bg-background-neutral-01 border-border-01",
            "p-3 overflow-auto max-h-[20rem] whitespace-pre-wrap wrap-break-word"
          )}
        >
          <Text font="main-ui-muted" color="text-02">
            Result
          </Text>
          <div className="mt-1">
            <Text as="p" font="main-content-body" color="text-04">
              {output}
            </Text>
          </div>
        </div>
      )}
    </div>
  );
}
