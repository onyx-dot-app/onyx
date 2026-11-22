"use client";

import { useTranslations } from "next-intl";
import { CommandBody } from "@/lib/timeline/components/bodies/CommandBody";
import type { ToolCardBodyProps } from "@/lib/timeline/craft/components/tool-cards/interfaces";

/**
 * BashBody - the command, its output and its exit code, in the shared execute
 * layout.
 */
export default function BashBody({ toolCall }: ToolCardBodyProps) {
  const t = useTranslations("craft.toolCards.bash");
  const tTimeline = useTranslations("chat.messages.timeline");
  return (
    <CommandBody
      command={toolCall.command}
      language="bash"
      prompt="$ "
      output={toolCall.rawOutput}
      emptyLabel={t("noOutput.label")}
      // The exit code the backend reports in `_meta.onyx`, when it has one.
      footer={
        toolCall.exitCode === undefined
          ? undefined
          : tTimeline("sandbox.exitCode.label", { exitCode: toolCall.exitCode })
      }
    />
  );
}
