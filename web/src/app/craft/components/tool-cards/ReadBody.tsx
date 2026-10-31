"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Text, Button } from "@opal/components";
import { SvgChevronDown } from "@opal/icons";
import { getLanguageFromPath } from "@/app/craft/utils/codeLanguage";
import { useCodeHighlighter } from "@/app/craft/hooks/useCodeHighlighter";
import ToolCardSurface, {
  ToolCardSection,
  MONO_STYLE,
} from "@/app/craft/components/tool-cards/ToolCardSurface";
import type { ToolCardBodyProps } from "@/app/craft/components/tool-cards/interfaces";

const PREVIEW_LINE_COUNT = 8;

/**
 * ReadBody - File preview for the read tool.
 *
 * Renders the first N lines with line numbers in a code-editor-style
 * card. Expands to show the full file on demand. Applies per-line
 * highlight.js syntax highlighting when the file extension matches a
 * registered language.
 */
export default function ReadBody({ toolCall }: ToolCardBodyProps) {
  const t = useTranslations("craft.toolCards.read");
  const [expanded, setExpanded] = useState(false);
  // The Read tool stores file content in rawOutput. The Write tool (when
  // routed here for new files) stores it in newContent instead. Fall back
  // so the same viewer renders both.
  const content = toolCall.rawOutput || toolCall.newContent;
  const language = useMemo(
    () => getLanguageFromPath(toolCall.description),
    [toolCall.description]
  );
  const highlight = useCodeHighlighter(!!language);

  if (!content) {
    return (
      <ToolCardSurface scroll={false}>
        <ToolCardSection>
          <Text font="secondary-mono" color="text-03">
            {t("emptyFile.label")}
          </Text>
        </ToolCardSection>
      </ToolCardSurface>
    );
  }

  const allLines = content.split("\n");
  const totalLines = allLines.length;
  const visibleLines = expanded
    ? allLines
    : allLines.slice(0, PREVIEW_LINE_COUNT);
  const hiddenCount = totalLines - visibleLines.length;

  return (
    <ToolCardSurface scroll={false}>
      <div className="overflow-auto max-h-[24rem] leading-tight hljs">
        <table className="w-full">
          <tbody>
            {visibleLines.map((line, idx) => {
              const html = highlight ? highlight(line, language) : null;
              return (
                <tr key={idx} className="align-baseline">
                  <td className="select-none ps-1 pe-1 py-0 text-end align-baseline w-6 border-e-[0.5px] border-border-01 bg-background-tint-01">
                    <Text font="secondary-mono" color="text-02">
                      {String(idx + 1)}
                    </Text>
                  </td>
                  <td
                    className="ps-2 pe-2 py-0 whitespace-pre-wrap wrap-break-word"
                    style={MONO_STYLE}
                  >
                    {html !== null ? (
                      <span dangerouslySetInnerHTML={{ __html: html || " " }} />
                    ) : (
                      <Text font="secondary-mono" color="text-04">
                        {line || " "}
                      </Text>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {hiddenCount > 0 && (
        <ToolCardSection
          divider
          tinted
          className="py-0.5 px-2 flex items-center justify-between"
        >
          <Text font="secondary-body" color="text-02">
            {t("moreLines.label", { count: hiddenCount })}
          </Text>
          <Button
            variant="default"
            prominence="tertiary"
            size="2xs"
            icon={SvgChevronDown}
            onClick={() => setExpanded(true)}
          >
            {t("showAll.button")}
          </Button>
        </ToolCardSection>
      )}
    </ToolCardSurface>
  );
}
