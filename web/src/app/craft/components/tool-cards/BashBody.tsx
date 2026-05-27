"use client";

import { useMemo } from "react";
import { cn } from "@opal/utils";
import { Text } from "@opal/components";
import { highlightLineHtml } from "@/app/craft/components/RawOutputBlock";
import type { ToolCardBodyProps } from "@/app/craft/components/tool-cards/interfaces";

/**
 * BashBody - command + stdout/stderr, rendered as a code-block surface.
 * The command sits at the top with a "$ " prefix and bash syntax
 * highlighting; the output (if any) sits below in plain text.
 */
export default function BashBody({ toolCall }: ToolCardBodyProps) {
  const command = toolCall.command;
  const output = toolCall.rawOutput;
  const commandHtml = useMemo(
    () => (command ? highlightLineHtml(command, "bash") : null),
    [command]
  );

  return (
    <div
      className={cn(
        "rounded-08 border-[0.5px] overflow-hidden px-3 py-2 max-h-[18rem] overflow-y-auto",
        "bg-background-neutral-01 border-border-01",
        "whitespace-pre-wrap wrap-break-word hljs"
      )}
    >
      {command && (
        <p
          style={{ fontFamily: "var(--font-dm-mono)", fontSize: "12px" }}
          className="text-text-04"
        >
          <span className="select-none text-text-02">{"$ "}</span>
          {commandHtml ? (
            <span dangerouslySetInnerHTML={{ __html: commandHtml }} />
          ) : (
            command
          )}
        </p>
      )}
      {output && (
        <Text as="p" font="secondary-mono" color="text-03">
          {output}
        </Text>
      )}
      {!command && !output && (
        <Text as="p" font="secondary-mono" color="text-03">
          No output
        </Text>
      )}
    </div>
  );
}
