"use client";

import { cn } from "@opal/utils";
import { Text } from "@opal/components";
import type { ToolCardBodyProps } from "@/app/craft/components/tool-cards/interfaces";

/**
 * BashBody - Code-block-styled output for the bash/execute tool.
 *
 * Renders captured stdout/stderr in a tinted, monospace block. The command
 * itself stays in the ToolCardHeader's secondary line; this body shows
 * only the output.
 */
export default function BashBody({ toolCall }: ToolCardBodyProps) {
  const output = toolCall.rawOutput;

  if (!output) {
    return (
      <div
        className={cn(
          "p-3 rounded-08 border-[0.5px]",
          "bg-background-neutral-02 border-border-01"
        )}
      >
        <Text font="secondary-mono" color="text-02">
          No output
        </Text>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "rounded-08 border-[0.5px] overflow-hidden",
        "bg-background-neutral-02 border-border-01"
      )}
    >
      <div
        className={cn(
          "p-3 overflow-auto max-h-[18rem]",
          "whitespace-pre-wrap wrap-break-word"
        )}
      >
        <Text as="p" font="secondary-mono" color="text-04">
          {output}
        </Text>
      </div>
    </div>
  );
}
