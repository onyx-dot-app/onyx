"use client";

import { useTranslations } from "next-intl";
import { CodePanel } from "@opal/components";
import { getLanguageFromPath } from "@/app/craft/utils/codeLanguage";
import { getLanguageHint } from "@/lib/timeline/craft/components/tool-cards/helpers";
import { useCodeLines } from "@/lib/timeline/components/bodies/useCodeLines";
import type { ToolCardBodyProps } from "@/lib/timeline/craft/components/tool-cards/interfaces";

/**
 * GenericBody - Fallback body for tools without a specialized renderer (a
 * skill, any other tool), as an Opal `CodePanel`: the tool's name and a copy
 * button, then the raw output as numbered lines, highlighted when a language
 * can be derived.
 */
export default function GenericBody({ toolCall }: ToolCardBodyProps) {
  const t = useTranslations("craft.toolCards.generic");
  const content = toolCall.rawOutput;
  const hint = getLanguageHint(toolCall);
  const lang = hint?.includes(".") ? getLanguageFromPath(hint) : hint;
  const lines = useCodeLines(content ?? "", lang);

  return (
    <CodePanel>
      <CodePanel.Header
        title={toolCall.toolName ?? toolCall.title}
        copyText={content || undefined}
      />
      {content ? (
        <CodePanel.Lines lineNumbers lines={lines} />
      ) : (
        <CodePanel.Output>{t("noOutput.label")}</CodePanel.Output>
      )}
    </CodePanel>
  );
}
