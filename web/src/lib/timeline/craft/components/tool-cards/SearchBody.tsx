"use client";

import { useTranslations } from "next-intl";
import { CommandBody } from "@/lib/timeline/components/bodies/CommandBody";
import type { ToolCardBodyProps } from "@/lib/timeline/craft/components/tool-cards/interfaces";

/**
 * SearchBody - a glob or grep search in the shared command layout: the tool's
 * name as the title, the pattern, and the matches as its output, each line
 * `path` (glob) or `path:line:snippet` (grep) as the tool emitted it.
 */
export default function SearchBody({ toolCall }: ToolCardBodyProps) {
  const t = useTranslations("craft.toolCards.search");
  return (
    <CommandBody
      command={toolCall.description}
      title={toolCall.toolName ?? toolCall.title}
      // A search that found nothing says so under its pattern.
      output={toolCall.rawOutput?.trim() || t("noMatches.label")}
      emptyLabel={t("noMatches.label")}
    />
  );
}
