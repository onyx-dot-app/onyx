"use client";

import { useMemo, useState } from "react";
import { Text, Button } from "@opal/components";
import { SvgChevronDown } from "@opal/icons";
import { getLanguageFromPath } from "@/app/craft/utils/codeLanguage";
import { useCodeHighlighter } from "@/app/craft/hooks/useCodeHighlighter";
import ToolCardSurface, {
  ToolCardSection,
  MONO_STYLE,
} from "@/lib/timeline/components/bodies/ToolCardSurface";

const PREVIEW_LINE_COUNT = 8;

interface FileBodyProps {
  content: string;
  /** The file's path or name; its extension picks the highlighting. */
  path: string;
  emptyLabel: string;
  moreLinesLabel: (count: number) => string;
  showAllLabel: string;
}

/**
 * The body of a read step: the first lines of a file with line numbers in a
 * code-editor-style card, highlighted when the extension matches a known
 * language. Expands to the whole file on demand. Shared by chat and Craft.
 */
export function FileBody({
  content,
  path,
  emptyLabel,
  moreLinesLabel,
  showAllLabel,
}: FileBodyProps) {
  const [expanded, setExpanded] = useState(false);
  const language = useMemo(() => getLanguageFromPath(path), [path]);
  const highlight = useCodeHighlighter(!!language);

  if (!content) {
    return (
      <ToolCardSurface scroll={false}>
        <ToolCardSection>
          <Text font="secondary-mono" color="text-03">
            {emptyLabel}
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
            {moreLinesLabel(hiddenCount)}
          </Text>
          <Button
            variant="default"
            prominence="tertiary"
            size="2xs"
            icon={SvgChevronDown}
            onClick={() => setExpanded(true)}
          >
            {showAllLabel}
          </Button>
        </ToolCardSection>
      )}
    </ToolCardSurface>
  );
}
