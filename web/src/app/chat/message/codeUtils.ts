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
      const codeTextMatch = codeBlockMatch[1];
      if (codeTextMatch !== undefined) {
        codeText = codeTextMatch;
      }
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
  // First detect if content is within a code block
  const codeBlockRegex = /^```[\s\S]*?```$/;
  const isCodeBlock = codeBlockRegex.test(content.trim());

  // If the entire content is a code block, don't process LaTeX
  if (isCodeBlock) {
    return content;
  }

  // Extract code blocks and replace with placeholders
  const codeBlocks: string[] = [];
  const withCodeBlocksReplaced = content.replace(/```[\s\S]*?```/g, (match) => {
    const placeholder = `___CODE_BLOCK_${codeBlocks.length}___`;
    codeBlocks.push(match);
    return placeholder;
  });

  // First, protect code-like expressions where $ is used for variables
  const codeProtected = withCodeBlocksReplaced.replace(
    /\b(\w+(?:\s*-\w+)*\s*(?:'[^']*')?)\s*\{[^}]*?\$\d+[^}]*?\}/g,
    (match) => {
      // Replace $ with a temporary placeholder in code contexts
      return match.replace(/\$/g, "___DOLLAR_PLACEHOLDER___");
    }
  );

  // Also protect common shell variable patterns like $1, $2, etc.
  const shellProtected = codeProtected.replace(
    /\b(?:print|echo|awk|sed|grep)\s+.*?\$\d+/g,
    (match) => match.replace(/\$/g, "___DOLLAR_PLACEHOLDER___")
  );

  // Protect inline code blocks with backticks
  const inlineCodeProtected = shellProtected.replace(/`[^`]+`/g, (match) => {
    return match.replace(/\$/g, "___DOLLAR_PLACEHOLDER___");
  });

  // Process LaTeX expressions now that code is protected
  // Valid LaTeX should have matching dollar signs with non-space chars surrounding content
  const processedForLatex = inlineCodeProtected.replace(
    /\$([^\s$][^$]*?[^\s$])\$/g,
    (_, equation) => `$${equation}$`
  );

  // Escape currency mentions
  const currencyEscaped = processedForLatex.replace(
    /\$(\d+(?:\.\d*)?)/g,
    (_, p1) => `\\$${p1}`
  );

  // Replace block-level LaTeX delimiters \[ \] with $$ $$
  const blockProcessed = currencyEscaped.replace(
    /\\\[([\s\S]*?)\\\]/g,
    (_, equation) => `$$${equation}$$`
  );

  // Replace inline LaTeX delimiters \( \) with $ $
  const inlineProcessed = blockProcessed.replace(
    /\\\(([\s\S]*?)\\\)/g,
    (_, equation) => `$${equation}$`
  );

  // Restore original dollar signs in code contexts
  const restoredDollars = inlineProcessed.replace(
    /___DOLLAR_PLACEHOLDER___/g,
    "$"
  );

  // Restore code blocks
  const restoredCodeBlocks = restoredDollars.replace(
    /___CODE_BLOCK_(\d+)___/g,
    (_, index) => codeBlocks[parseInt(index)] ?? ""
  );

  return restoredCodeBlocks;
};
