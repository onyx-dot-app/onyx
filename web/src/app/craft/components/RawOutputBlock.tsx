"use client";

import { useMemo } from "react";
import { cn } from "@/lib/utils";
import hljs from "highlight.js/lib/core";

// Import highlight.js theme styles (dark mode Atom One Dark)
import "@/app/app/message/custom-code-styles.css";

// Register common languages
import javascript from "highlight.js/lib/languages/javascript";
import typescript from "highlight.js/lib/languages/typescript";
import python from "highlight.js/lib/languages/python";
import json from "highlight.js/lib/languages/json";
import css from "highlight.js/lib/languages/css";
import xml from "highlight.js/lib/languages/xml"; // includes HTML
import bash from "highlight.js/lib/languages/bash";
import yaml from "highlight.js/lib/languages/yaml";
import markdown from "highlight.js/lib/languages/markdown";
import sql from "highlight.js/lib/languages/sql";

hljs.registerLanguage("javascript", javascript);
hljs.registerLanguage("js", javascript);
hljs.registerLanguage("jsx", javascript);
hljs.registerLanguage("typescript", typescript);
hljs.registerLanguage("ts", typescript);
hljs.registerLanguage("tsx", typescript);
hljs.registerLanguage("python", python);
hljs.registerLanguage("py", python);
hljs.registerLanguage("json", json);
hljs.registerLanguage("css", css);
hljs.registerLanguage("html", xml);
hljs.registerLanguage("xml", xml);
hljs.registerLanguage("bash", bash);
hljs.registerLanguage("sh", bash);
hljs.registerLanguage("shell", bash);
hljs.registerLanguage("yaml", yaml);
hljs.registerLanguage("yml", yaml);
hljs.registerLanguage("markdown", markdown);
hljs.registerLanguage("md", markdown);
hljs.registerLanguage("sql", sql);

/**
 * Get language from file extension
 */
function getLanguageFromPath(filePath: string | undefined): string | undefined {
  if (!filePath) return undefined;
  const ext = filePath.split(".").pop()?.toLowerCase();
  if (!ext) return undefined;

  const langMap: Record<string, string> = {
    js: "javascript",
    jsx: "javascript",
    ts: "typescript",
    tsx: "typescript",
    py: "python",
    json: "json",
    css: "css",
    html: "html",
    xml: "xml",
    sh: "bash",
    bash: "bash",
    yaml: "yaml",
    yml: "yaml",
    md: "markdown",
    sql: "sql",
  };

  return langMap[ext];
}

interface RawOutputBlockProps {
  content: string;
  maxHeight?: string;
  /** File path to derive language from, or explicit language name */
  language?: string;
}

/**
 * RawOutputBlock - Scrollable code block for tool output
 *
 * Displays raw output in a dark monospace container with
 * horizontal and vertical scrolling. Applies syntax highlighting
 * when a language can be determined.
 */
export default function RawOutputBlock({
  content,
  maxHeight = "300px",
  language,
}: RawOutputBlockProps) {
  const highlightedHtml = useMemo(() => {
    if (!content) return null;

    // Try to determine language from file path or explicit language
    const lang = language?.includes(".")
      ? getLanguageFromPath(language)
      : language;

    try {
      if (lang && hljs.getLanguage(lang)) {
        return hljs.highlight(content, { language: lang }).value;
      }
      // Don't auto-detect for plain output (like command results)
      return null;
    } catch {
      return null;
    }
  }, [content, language]);

  if (!content) {
    return (
      <div
        className={cn(
          "p-3 rounded-08 border",
          // Match hljs theme: light=#fafafa, dark=#151617
          "bg-[#fafafa] border-[#fafafa] dark:bg-[#151617] dark:border-[#151617]",
          "text-text-03 text-xs"
        )}
        style={{ fontFamily: "var(--font-dm-mono)" }}
      >
        No output yet...
      </div>
    );
  }

  return (
    <div
      className={cn(
        "p-3 rounded-08 border",
        // Match hljs theme: light=#fafafa, dark=#151617
        "bg-[#fafafa] border-[#fafafa] dark:bg-[#151617] dark:border-[#151617]",
        "text-xs overflow-auto"
      )}
      style={{
        fontFamily: "var(--font-dm-mono)",
        maxHeight,
      }}
    >
      {highlightedHtml ? (
        <pre
          className="whitespace-pre-wrap break-words m-0 hljs"
          dangerouslySetInnerHTML={{ __html: highlightedHtml }}
        />
      ) : (
        <pre className="whitespace-pre-wrap break-words m-0">{content}</pre>
      )}
    </div>
  );
}
