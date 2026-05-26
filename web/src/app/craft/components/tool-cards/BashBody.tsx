"use client";

import { Text } from "@opal/components";
import type { ToolCardBodyProps } from "@/app/craft/components/tool-cards/interfaces";

/**
 * BashBody - stdout/stderr from the bash/execute tool, rendered under the
 * card-wide quote-bar pattern. Mirrors WebFetchBody for visual parity.
 */
export default function BashBody({ toolCall }: ToolCardBodyProps) {
  const output = toolCall.rawOutput;

  return (
    <div className="border-l border-border-02 pl-3 overflow-auto max-h-[18rem] whitespace-pre-wrap wrap-break-word">
      <Text as="p" font="secondary-mono" color="text-03">
        {output || "No output"}
      </Text>
    </div>
  );
}
