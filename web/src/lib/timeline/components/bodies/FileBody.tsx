"use client";

import { useMemo, useState } from "react";
import { Button, CodePanel } from "@opal/components";
import { SvgChevronDown } from "@opal/icons";
import { getLanguageFromPath } from "@/app/craft/utils/codeLanguage";
import { useCodeLines } from "@/lib/timeline/components/bodies/useCodeLines";

const PREVIEW_LINE_COUNT = 8;

interface FileBodyProps {
  content: string;
  /** The file's path or name; its extension picks the highlighting. */
  path: string;
  emptyLabel: string;
  moreLinesLabel: (count: number) => string;
  showAllLabel: string;
  /**
   * The content is excerpts of a file, not the file: it shows whole, without
   * line numbers, since its lines are not the file's.
   */
  excerpt?: boolean;
}

/**
 * The body of a read step, as an Opal `CodePanel`: a title row with the path
 * and a copy button, then the first lines of the file with line numbers,
 * highlighted when the extension matches a known language. Expands to the
 * whole file on demand. Shared by chat and Craft.
 */
export function FileBody({
  content,
  path,
  emptyLabel,
  moreLinesLabel,
  showAllLabel,
  excerpt = false,
}: FileBodyProps) {
  const [expanded, setExpanded] = useState(false);
  const language = useMemo(() => getLanguageFromPath(path), [path]);
  // Highlight only the lines on screen; the rest waits until the file is
  // expanded.
  const totalLines = useMemo(() => content.split("\n").length, [content]);
  const showAll = expanded || excerpt;
  const shownText = useMemo(
    () =>
      showAll ? content : content.split("\n", PREVIEW_LINE_COUNT).join("\n"),
    [content, showAll]
  );
  const visibleLines = useCodeLines(shownText, language);

  if (!content) {
    return (
      <CodePanel>
        {path && <CodePanel.Header title={path} />}
        <CodePanel.Output>{emptyLabel}</CodePanel.Output>
      </CodePanel>
    );
  }

  const hiddenCount = totalLines - visibleLines.length;

  return (
    <CodePanel>
      {path && <CodePanel.Header title={path} copyText={content} />}
      <CodePanel.Lines
        lineNumbers={!excerpt}
        copyText={path ? undefined : content}
        lines={visibleLines}
      />
      {hiddenCount > 0 && (
        <CodePanel.Footer
          title={moreLinesLabel(hiddenCount)}
          rightChildren={
            <Button
              variant="default"
              prominence="tertiary"
              size="2xs"
              icon={SvgChevronDown}
              onClick={() => setExpanded(true)}
            >
              {showAllLabel}
            </Button>
          }
        />
      )}
    </CodePanel>
  );
}
