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
        const children = (node.props as any).children;
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

const QUOTE_MARKER_REGEX = /^ {0,3}> ?/;
const LIST_MARKER_REGEX = /^[ \t]*(?:[-*+]|\d{1,9}[.)])(?:[ \t]+|$)/;
const FENCE_REGEX = /^([ \t]*)(`{3,}|~{3,})(.*)$/;

const stripQuotes = (
  line: string,
  maxDepth: number = Infinity
): { depth: number; rest: string } => {
  let depth = 0;
  let rest = line;
  while (depth < maxDepth) {
    const match = QUOTE_MARKER_REGEX.exec(rest);
    if (!match) break;
    rest = rest.slice(match[0].length);
    depth++;
  }
  return { depth, rest };
};

// Column width with CommonMark tab stops (multiples of 4).
const widthOf = (text: string): number => {
  let column = 0;
  for (const char of text) {
    column = char === "\t" ? column + 4 - (column % 4) : column + 1;
  }
  return column;
};

const indentOf = (text: string): number =>
  widthOf(/^[ \t]*/.exec(text)?.[0] ?? "");

type FenceRole = "open" | "close" | "code" | "text";

interface FenceLine {
  role: FenceRole;
  // For bare backtick openers: index just past the fence characters.
  bareFenceEnd?: number;
}

interface OpenFence {
  fence: string;
  quoteDepth: number;
  // Content column of the enclosing list item (0 outside lists).
  base: number;
}

// Classifies each line by fenced-code role (simplified CommonMark). Inline
// ``` in prose is ignored; closers need the opener's char, >= its length and
// no info string; a block also ends when its blockquote or list item ends.
// A trailing unclosed block (mid-stream) stays "code". Mirrors
// CodeFenceTracker in backend/onyx/chat/citation_processor.py.
const classifyFenceLines = (lines: string[]): FenceLine[] => {
  let open: OpenFence | null = null;
  let listColumn = 0;

  const containerEnded = (fence: OpenFence, line: string): boolean => {
    const { depth, rest } = stripQuotes(line, fence.quoteDepth);
    if (rest.trim() === "") return depth < fence.quoteDepth;
    return depth < fence.quoteDepth || indentOf(rest) < fence.base;
  };

  return lines.map((line): FenceLine => {
    if (open !== null) {
      if (!containerEnded(open, line)) {
        const { rest } = stripQuotes(line, open.quoteDepth);
        const match = FENCE_REGEX.exec(rest);
        const fence = match?.[2] ?? "";
        if (
          match &&
          indentOf(rest) <= open.base + 3 &&
          fence[0] === open.fence[0] &&
          fence.length >= open.fence.length &&
          (match[3] ?? "").trim() === ""
        ) {
          open = null;
          return { role: "close" };
        }
        return { role: "code" };
      }
      open = null;
    }

    const { depth, rest } = stripQuotes(line);
    if (rest.trim() === "") return { role: "text" };
    const marker = LIST_MARKER_REGEX.exec(rest);
    const fenceStart = marker ? marker[0].length : 0;
    if (marker) {
      listColumn = widthOf(marker[0]);
    } else if (indentOf(rest) < listColumn) {
      listColumn = 0;
    }
    const match = FENCE_REGEX.exec(rest.slice(fenceStart));
    if (!match) return { role: "text" };
    const indentText = match[1] ?? "";
    const indent = widthOf(indentText);
    // 4+ spaces past the container column is an indented code block.
    if (marker ? indent > 0 : indent > listColumn + 3) return { role: "text" };
    const fence = match[2] ?? "";
    const info = match[3] ?? "";
    // Backtick fences cannot have backticks in the info string.
    if (fence.startsWith("`") && info.includes("`")) return { role: "text" };
    open = { fence, quoteDepth: depth, base: listColumn };
    const bare = fence.startsWith("`") && info.trim() === "";
    return {
      role: "open",
      bareFenceEnd: bare
        ? line.length -
          rest.length +
          fenceStart +
          indentText.length +
          fence.length
        : undefined,
    };
  });
};

// Labels bare opening backtick fences as `plaintext`; closers stay bare.
export const labelBareCodeFences = (content: string): string => {
  const lines = content.split("\n");
  const classified = classifyFenceLines(lines);
  return lines
    .map((line, i) => {
      const end = classified[i]?.bareFenceEnd;
      return end === undefined ? line : `${line.slice(0, end)}plaintext`;
    })
    .join("\n");
};

// Replaces each fenced code block, including an unclosed trailing one
// (mid-stream), with the string from `replace`.
const replaceFencedCodeBlocks = (
  content: string,
  replace: (block: string) => string
): string => {
  const lines = content.split("\n");
  const classified = classifyFenceLines(lines);
  const out: string[] = [];
  let block: string[] | null = null;
  for (const [i, line] of lines.entries()) {
    const role = classified[i]?.role;
    if (block && (role === "code" || role === "close")) {
      block.push(line);
      if (role === "close") {
        out.push(replace(block.join("\n")));
        block = null;
      }
      continue;
    }
    if (block) {
      // The block ended with its container.
      out.push(replace(block.join("\n")));
      block = null;
    }
    if (role === "open") {
      block = [line];
    } else {
      out.push(line);
    }
  }
  if (block) out.push(replace(block.join("\n")));
  return out.join("\n");
};

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
  const withCodeBlocksReplaced = replaceFencedCodeBlocks(content, (block) => {
    const placeholder = `___CODE_BLOCK_${codeBlocks.length}___`;
    codeBlocks.push(block);
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

// Hides code blocks behind temporary markers so the caller can count `$`
// or `$$` without including ones that live inside code. Closed
// ```...``` blocks become markers. A leftover ``` (mid-stream, no closer
// yet) is sliced off as `tail` so the caller skips it entirely.
// `restore` puts the original code blocks back.
const protectCodeFences = (
  content: string,
  label: string
): {
  head: string;
  tail: string;
  restore: (s: string) => string;
} => {
  const nonce = Math.random().toString(36).slice(2);
  const blocks: string[] = [];
  const replaced = content.replace(/```[\s\S]*?```/g, (match) => {
    blocks.push(match);
    return `___${label}_${nonce}_CB_${blocks.length - 1}___`;
  });

  const lastOpen = replaced.lastIndexOf("```");
  const head = lastOpen >= 0 ? replaced.slice(0, lastOpen) : replaced;
  const tail = lastOpen >= 0 ? replaced.slice(lastOpen) : "";

  return {
    head,
    tail,
    restore: (s) =>
      s.replace(
        new RegExp(`___${label}_${nonce}_CB_(\\d+)___`, "g"),
        (_, i) => blocks[Number(i)] ?? ""
      ),
  };
};

// Mid-stream the buffer can hold `$$x = y` with no closing `$$` yet.
// Escape the lone `$$` to `\$\$` so the renderer shows it as literal
// text instead of broken math. Once the closing `$$` arrives, the count
// is balanced again and we leave it alone — the formula renders.
export const escapeIncompleteBlockMath = (content: string): string => {
  const { head, tail, restore } = protectCodeFences(content, "MATHESC");

  // split on `$$`. Even number of pieces ⇒ odd number of `$$` ⇒ one is
  // unmatched. Replace the last separator with an escaped `\$\$`.
  const parts = head.split("$$");
  let processedHead = head;
  if (parts.length % 2 === 0) {
    const last = parts[parts.length - 1] ?? "";
    const before = parts.slice(0, -1).join("$$");
    processedHead = `${before}\\$\\$${last}`;
  }

  return restore(processedHead + tail);
};

// Same idea as escapeIncompleteBlockMath, but for single `$` (inline
// math). Mid-stream `The cost is $\frac{a}{` has one unmatched `$` —
// escape it to `\$` so the renderer doesn't open a broken inline-math
// span. Runs AFTER preprocessLaTeX so currency dollars are already
// `\$5` (and won't be miscounted as inline-math openers).
export const escapeIncompleteInlineMath = (content: string): string => {
  const {
    head: rawHead,
    tail,
    restore: restoreFences,
  } = protectCodeFences(content, "INLMATH");

  // Hide balanced `$$...$$` blocks too — their interior `$` is part of
  // block math, not a separate inline delimiter.
  const blockMath: string[] = [];
  const blockNonce = Math.random().toString(36).slice(2);
  let working = rawHead.replace(/\$\$[\s\S]*?\$\$/g, (match) => {
    blockMath.push(match);
    return `___INLMATH_${blockNonce}_BM_${blockMath.length - 1}___`;
  });

  // Walk the string; collect positions of `$` that aren't already
  // escaped (i.e. preceding char isn't `\`). Odd count → escape the
  // last one.
  const indices: number[] = [];
  for (let i = 0; i < working.length; i++) {
    if (working[i] === "$" && (i === 0 || working[i - 1] !== "\\")) {
      indices.push(i);
    }
  }
  if (indices.length % 2 === 1) {
    const last = indices[indices.length - 1] as number;
    working = working.slice(0, last) + "\\$" + working.slice(last + 1);
  }

  // Restore in reverse order: block-math markers first (they may
  // contain code-fence markers inside them), then code fences.
  const restoredBlocks = working.replace(
    new RegExp(`___INLMATH_${blockNonce}_BM_(\\d+)___`, "g"),
    (_, i) => blockMath[Number(i)] ?? ""
  );
  return restoreFences(restoredBlocks + tail);
};
