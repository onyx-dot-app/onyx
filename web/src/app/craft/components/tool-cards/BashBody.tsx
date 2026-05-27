"use client";

import { cn } from "@opal/utils";
import { Text } from "@opal/components";
import type { ToolCardBodyProps } from "@/app/craft/components/tool-cards/interfaces";

/**
 * BashBody - stdout/stderr from the bash/execute tool, rendered as a
 * code-block surface (matches DiffBody / ReadBody, which also display code).
 */
export default function BashBody({ toolCall }: ToolCardBodyProps) {
  const output = toolCall.rawOutput;

  return (
    <div
      className={cn(
        "rounded-08 border-[0.5px] overflow-hidden px-3 py-2 max-h-[18rem] overflow-y-auto",
        "bg-background-neutral-01 border-border-01",
        "whitespace-pre-wrap wrap-break-word"
      )}
    >
      <Text as="p" font="secondary-mono" color="text-03">
        {output || "No output"}
      </Text>
    </div>
  );
}
