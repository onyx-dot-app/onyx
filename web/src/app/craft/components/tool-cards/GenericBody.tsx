"use client";

import RawOutputBlock from "@/app/craft/components/RawOutputBlock";
import { getLanguageHint } from "@/app/craft/components/tool-cards/helpers";
import type { ToolCardBodyProps } from "@/app/craft/components/tool-cards/interfaces";

/**
 * GenericBody - Fallback body for tools that don't have a specialized renderer.
 *
 * Just renders the tool's raw output in a syntax-highlighted block.
 */
export default function GenericBody({ toolCall }: ToolCardBodyProps) {
  return (
    <RawOutputBlock
      content={toolCall.rawOutput}
      language={getLanguageHint(toolCall)}
    />
  );
}
