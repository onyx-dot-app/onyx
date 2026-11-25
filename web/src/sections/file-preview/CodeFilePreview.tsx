"use client";

import { useMemo } from "react";
import { cn } from "@opal/utils";
import { useHighlightedLines } from "@/lib/codeHighlight/hooks";
import { indentJson } from "@/lib/filePreview/indentJson";

// Longer text shows without highlighting, which would take seconds.
export const MAX_HIGHLIGHTED_CHARACTERS = 100_000;

interface CodeFilePreviewProps {
  text: string;
  // A Shiki language id or alias; `plaintext` wraps lines
  language: string;
}

/**
 * Code, data and plain text on a code background. Grammars load on demand
 * and highlight after paint; until then, and for unknown languages, the text
 * shows plain. Single-line
 * JSON shows indented. Code shows line numbers; plain text wraps instead.
 */
export function CodeFilePreview({ text, language }: CodeFilePreviewProps) {
  const plaintext = language === "plaintext";
  const shown = useMemo(
    () => (language === "json" ? indentJson(text) : text),
    [text, language]
  );
  const highlight = !plaintext && shown.length <= MAX_HIGHLIGHTED_CHARACTERS;
  const highlightedLines = useHighlightedLines(
    shown,
    highlight ? language : undefined
  );
  const lineNumbers = useMemo(
    () =>
      plaintext
        ? null
        : Array.from(
            { length: shown.split("\n").length },
            (_, index) => index + 1
          ).join("\n"),
    [shown, plaintext]
  );

  return (
    <div
      dir="ltr"
      className="h-full overflow-auto bg-background-code-01 p-4 pb-16"
    >
      {lineNumbers !== null && (
        <pre
          aria-hidden
          className="float-start m-0 select-none pe-4 text-end font-mono text-xs text-text-03"
        >
          {lineNumbers}
        </pre>
      )}
      <pre
        className={cn(
          "m-0 font-mono text-xs text-text-04",
          plaintext ? "whitespace-pre-wrap wrap-break-word" : "whitespace-pre"
        )}
      >
        {highlightedLines ? (
          <code
            dangerouslySetInnerHTML={{ __html: highlightedLines.join("\n") }}
          />
        ) : (
          <code>{shown}</code>
        )}
      </pre>
    </div>
  );
}
