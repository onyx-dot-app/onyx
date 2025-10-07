"use client";
import { unified } from "unified";
import remarkParse from "remark-parse";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import remarkRehype from "remark-rehype";
import rehypePrism from "rehype-prism-plus";
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

// For copying the entire content
export function copyAll(content: string) {
  // Convert markdown to HTML using unified ecosystem
  unified()
    .use(remarkParse)
    .use(remarkGfm)
    .use(remarkMath)
    .use(remarkRehype)
    .use(rehypePrism, { ignoreMissing: true })
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
