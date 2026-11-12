"use client";

import { useTranslations } from "next-intl";
import { FileBody } from "@/lib/timeline/components/bodies/FileBody";
import type { ToolCardBodyProps } from "@/lib/timeline/craft/components/tool-cards/interfaces";

/**
 * ReadBody - the read tool's file, in the shared read layout. The Write tool
 * (when routed here for new files) keeps its content in `newContent`.
 */
export default function ReadBody({ toolCall }: ToolCardBodyProps) {
  const t = useTranslations("craft.toolCards.read");
  return (
    <FileBody
      content={toolCall.rawOutput || toolCall.newContent || ""}
      path={toolCall.description}
      emptyLabel={t("emptyFile.label")}
      moreLinesLabel={(count) => t("moreLines.label", { count })}
      showAllLabel={t("showAll.button")}
    />
  );
}
