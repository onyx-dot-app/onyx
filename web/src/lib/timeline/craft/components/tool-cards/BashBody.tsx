"use client";

import { useTranslations } from "next-intl";
import { CommandBody } from "@/lib/timeline/components/bodies/CommandBody";
import type { ToolCardBodyProps } from "@/lib/timeline/craft/components/tool-cards/interfaces";

/** BashBody - the command and its output, in the shared execute layout. */
export default function BashBody({ toolCall }: ToolCardBodyProps) {
  const t = useTranslations("craft.toolCards.bash");
  return (
    <CommandBody
      command={toolCall.command}
      language="bash"
      prompt="$ "
      output={toolCall.rawOutput}
      emptyLabel={t("noOutput.label")}
    />
  );
}
