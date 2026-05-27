"use client";

import { Text, Tag } from "@opal/components";
import { SvgBubbleText } from "@opal/icons";
import type { ToolCardBodyProps } from "@/app/craft/components/tool-cards/interfaces";

/**
 * TaskBody - Renderer for the task (subagent) tool.
 *
 * Shows the subagent type badge, the prompt, and the final output. Each
 * content block sits inside the card-wide quote-bar pattern.
 */
export default function TaskBody({ toolCall }: ToolCardBodyProps) {
  const subagentType = toolCall.subagentType;
  const prompt = toolCall.command || toolCall.rawOutput;
  const output = toolCall.taskOutput;

  return (
    <div className="px-3 flex flex-col gap-3">
      {subagentType && (
        <div className="flex items-center gap-2">
          <Tag icon={SvgBubbleText} title={subagentType} color="purple" />
          <Text font="main-ui-muted" color="text-02">
            subagent
          </Text>
        </div>
      )}

      {prompt && (
        <div>
          <Text font="main-ui-muted" color="text-02">
            Prompt
          </Text>
          <div className="mt-1 overflow-auto max-h-[14rem] whitespace-pre-wrap wrap-break-word">
            <Text as="p" font="secondary-body" color="text-04">
              {prompt}
            </Text>
          </div>
        </div>
      )}

      {output && (
        <div>
          <Text font="main-ui-muted" color="text-02">
            Result
          </Text>
          <div className="mt-1 overflow-auto max-h-[20rem] whitespace-pre-wrap wrap-break-word">
            <Text as="p" font="main-content-body" color="text-04">
              {output}
            </Text>
          </div>
        </div>
      )}
    </div>
  );
}
