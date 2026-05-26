"use client";

import { cn } from "@opal/utils";
import { Text } from "@opal/components";
import type { ToolCardBodyProps } from "@/app/craft/components/tool-cards/interfaces";

/**
 * BashBody - Code-block-styled output for the bash/execute tool.
 *
 * Renders captured stdout/stderr indented under a left quote-bar — same
 * pattern as ThinkingCard, so the header's hover tint never collides with
 * the body's background.
 */
export default function BashBody({ toolCall }: ToolCardBodyProps) {
  const output = toolCall.rawOutput;

  if (!output) {
    return (
      <div className="border-l border-border-02 pl-3">
        <Text font="secondary-mono" color="text-02">
          No output
        </Text>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "border-l border-border-02 pl-3 max-h-[18rem] overflow-auto",
        "whitespace-pre-wrap wrap-break-word"
      )}
    >
      <Text as="p" font="secondary-mono" color="text-04">
        {output}
      </Text>
    </div>
  );
}
