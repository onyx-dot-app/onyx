"use client";
import { unified } from "unified";
import remarkParse from "remark-parse";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import remarkRehype from "remark-rehype";
import rehypeHighlight from "rehype-highlight";
import rehypeKatex from "rehype-katex";
import rehypeSanitize from "rehype-sanitize";
import rehypeStringify from "rehype-stringify";

export function handleCopy(
  event: React.ClipboardEvent,
  markdownRef: React.RefObject<HTMLDivElement>
) {
  // Check if we have a selection
  const selection = window.getSelection();
  if (!selection?.rangeCount) return;

  const range = selection.getRangeAt(0);

  // If selection is within our markdown container
  if (
    markdownRef.current &&
    markdownRef.current.contains(range.commonAncestorContainer)
  ) {
    event.preventDefault();

    // Clone selection to get the HTML
    const fragment = range.cloneContents();
    const tempDiv = document.createElement("div");
    tempDiv.appendChild(fragment);

    // Create clipboard data with both HTML and plain text
    event.clipboardData.setData("text/html", tempDiv.innerHTML);
    event.clipboardData.setData("text/plain", selection.toString());
  }
}

// Convert markdown tables to TSV format for spreadsheet compatibility
export function convertMarkdownTablesToTsv(content: string): string {
  const lines = content.split("\n");
  const result: string[] = [];

  for (const line of lines) {
    // Check if line is a markdown table row (starts and ends with |)
    const trimmed = line.trim();
    if (trimmed.startsWith("|") && trimmed.endsWith("|")) {
      // Check if it's a separator row (contains only |, -, :, and spaces)
      if (/^\|[\s\-:|\s]+\|$/.test(trimmed)) {
        // Skip separator rows
        continue;
      }
      // Convert table row: split by |, trim cells, join with tabs
      const cells = trimmed
        .slice(1, -1) // Remove leading and trailing |
        .split("|")
        .map((cell) => cell.trim());
      result.push(cells.join("\t"));
    } else {
      result.push(line);
    }
  }

  return result.join("\n");
}

// For copying the entire content
export function copyAll(content: string) {
  // Convert markdown to HTML using unified ecosystem
  unified()
    .use(remarkParse)
    .use(remarkGfm)
    .use(remarkMath)
    .use(remarkRehype)
    .use(rehypeHighlight)
    .use(rehypeKatex)
    .use(rehypeSanitize)
    .use(rehypeStringify)
    .process(content)
    .then((file: any) => {
      const htmlContent = String(file);

      // Create clipboard data
      const clipboardItem = new ClipboardItem({
        "text/html": new Blob([htmlContent], { type: "text/html" }),
        "text/plain": new Blob([content], { type: "text/plain" }),
      });

      navigator.clipboard.write([clipboardItem]);
    });
}
