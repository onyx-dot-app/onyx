import React from "react";

export function extractCodeText(
  node: any,
  content: string,
  children: React.ReactNode
): string {
  let codeText: string | null = null;

  if (
    node?.position?.start?.offset != null &&
    node?.position?.end?.offset != null
  ) {
    codeText = content
      .slice(node.position.start.offset, node.position.end.offset)
      .trim();

    // Match code block with optional language declaration
    const codeBlockMatch = codeText.match(/^```[^\n]*\n([\s\S]*?)\n?```$/);
    if (codeBlockMatch) {
      codeText = codeBlockMatch[1];
    }

    // Normalize indentation
    const codeLines = codeText.split("\n");
    const minIndent = codeLines
      .filter((line) => line.trim().length > 0)
      .reduce((min, line) => {
        const match = line.match(/^\s*/);
        return Math.min(min, match ? match[0].length : min);
      }, Infinity);

    const formattedCodeLines = codeLines.map((line) => line.slice(minIndent));
    codeText = formattedCodeLines.join("\n").trim();
  } else {
    // Fallback if position offsets are not available
    const extractTextFromReactNode = (node: React.ReactNode): string => {
      if (typeof node === "string") return node;
      if (typeof node === "number") return String(node);
      if (!node) return "";

      if (React.isValidElement(node)) {
        const children = node.props.children;
        if (Array.isArray(children)) {
          return children.map(extractTextFromReactNode).join("");
        }
        return extractTextFromReactNode(children);
      }

      if (Array.isArray(node)) {
        return node.map(extractTextFromReactNode).join("");
      }

      return "";
    };

    codeText = extractTextFromReactNode(children);
  }

  return codeText || "";
}

// We must preprocess LaTeX in the LLM output to avoid improper formatting
export const preprocessLaTeX = (content: string) => {
  // 1) Escape dollar signs used outside of LaTeX context
  const escapedCurrencyContent = content.replace(
    /\$(\d+(?:\.\d*)?)/g,
    (_, p1) => `\\$${p1}`
  );

  // 2) Replace block-level LaTeX delimiters \[ \] with $$ $$
  const blockProcessedContent = escapedCurrencyContent.replace(
    /\\\[([\s\S]*?)\\\]/g,
    (_, equation) => `$$${equation}$$`
  );

  // 3) Replace inline LaTeX delimiters \( \) with $ $
  const inlineProcessedContent = blockProcessedContent.replace(
    /\\\(([\s\S]*?)\\\)/g,
    (_, equation) => `$${equation}$`
  );

  return inlineProcessedContent;
};
