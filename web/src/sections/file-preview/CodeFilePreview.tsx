"use client";

import { useMemo, type ReactNode } from "react";
import type { RootContent } from "hast";
import { createLowlight } from "lowlight";
import { cn } from "@opal/utils";
import { useHighlightLanguages } from "@/hooks/useHighlightLanguages";
import "@/app/app/message/custom-code-styles.css";

// Longer text shows without highlighting, which would block the page.
// Markdown longer than this shows as source.
export const MAX_HIGHLIGHTED_CHARACTERS = 200_000;

// Grammars register once, when the first preview loads them
const lowlight = createLowlight();

function renderHighlighted(nodes: RootContent[]): ReactNode[] {
  return nodes.map((node, index) => {
    if (node.type === "text") return node.value;
    if (node.type !== "element") return null;
    const className = node.properties.className;
    return (
      <span
        key={index}
        className={Array.isArray(className) ? className.join(" ") : undefined}
      >
        {renderHighlighted(node.children)}
      </span>
    );
  });
}

interface CodeFilePreviewProps {
  text: string;
  // A highlight.js language name or alias; `plaintext` wraps lines
  language: string;
}

/**
 * Code, data and plain text on a code background. Grammars load on demand;
 * until then, and for unknown languages, the text shows plain. JSON shows
 * indented.
 */
export function CodeFilePreview({ text, language }: CodeFilePreviewProps) {
  const plaintext = language === "plaintext";
  const shown = useMemo(() => {
    if (language !== "json") return text;
    try {
      return JSON.stringify(JSON.parse(text), null, 2);
    } catch {
      // Malformed JSON shows as it is
      return text;
    }
  }, [text, language]);
  const highlight = !plaintext && shown.length <= MAX_HIGHLIGHTED_CHARACTERS;
  const languages = useHighlightLanguages(highlight);
  const content = useMemo(() => {
    if (!highlight || !languages) return shown;
    if (lowlight.listLanguages().length === 0) lowlight.register(languages);
    if (!lowlight.registered(language)) return shown;
    return renderHighlighted(lowlight.highlight(language, shown).children);
  }, [shown, language, highlight, languages]);

  return (
    <div className="h-full overflow-auto bg-background-code-01 p-4 pb-16">
      <pre
        dir="ltr"
        className={cn(
          "hljs m-0 font-mono text-xs",
          plaintext ? "whitespace-pre-wrap wrap-break-word" : "whitespace-pre"
        )}
      >
        <code>{content}</code>
      </pre>
    </div>
  );
}
