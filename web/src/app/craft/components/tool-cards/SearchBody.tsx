"use client";

import { Text } from "@opal/components";
import ToolCardSurface, {
  ToolCardSection,
} from "@/app/craft/components/tool-cards/ToolCardSurface";
import type { ToolCardBodyProps } from "@/app/craft/components/tool-cards/interfaces";

/**
 * SearchBody - glob/grep results rendered as a single monospace block, matching
 * the command body. Each result line is `path` (glob) or `path:line:snippet`
 * (grep) exactly as the tool emitted it — no per-line icon rows.
 */
export default function SearchBody({ toolCall }: ToolCardBodyProps) {
  const output = toolCall.rawOutput?.trim();

  if (!output) {
    return (
      <ToolCardSurface>
        <ToolCardSection>
          <Text font="secondary-mono" color="text-02">
            No matches
          </Text>
        </ToolCardSection>
      </ToolCardSurface>
    );
  }

  return (
    <ToolCardSurface>
      <ToolCardSection className="whitespace-pre-wrap wrap-break-word">
        <Text as="p" font="secondary-mono" color="text-03">
          {output}
        </Text>
      </ToolCardSection>
    </ToolCardSurface>
  );
}
