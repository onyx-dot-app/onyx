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

export const markdownToHtml = (content: string): string => {
  if (!content || !content.trim()) {
    return "";
  }

  // Basic markdown to HTML conversion for common patterns
  const processedContent = content
    .replace(/(\*\*|__)((?:(?!\1).)*?)\1/g, "<strong>$2</strong>") // Bold with ** or __, non-greedy and no nesting
    .replace(/(\*|_)([^*_\n]+?)\1(?!\*|_)/g, "<em>$2</em>"); // Italic with * or _

  // Handle code blocks and links
  const withCodeAndLinks = processedContent
    .replace(/`([^`]+)`/g, "<code>$1</code>") // Inline code
    .replace(
      /```(\w*)\n([\s\S]*?)```/g,
      (_, lang, code) =>
        `<pre><code class="language-${lang}">${code.trim()}</code></pre>`
    ) // Code blocks
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2">$1</a>'); // Links

  // Handle paragraphs
  return withCodeAndLinks
    .split(/\n\n+/)
    .map((para) => para.trim())
    .filter((para) => para.length > 0)
    .map((para) => `<p>${para}</p>`)
    .join("\n");
};

interface MarkdownSegment {
  type: "text" | "link" | "code" | "bold" | "italic" | "codeblock";
  text: string; // The visible/plain text
  raw: string; // The raw markdown including syntax
  length: number; // Length of the visible text
}

export function parseMarkdownToSegments(markdown: string): MarkdownSegment[] {
  if (!markdown) {
    return [];
  }

  const segments: MarkdownSegment[] = [];
  let currentIndex = 0;
  const maxIterations = markdown.length * 2; // Prevent infinite loops
  let iterations = 0;

  while (currentIndex < markdown.length && iterations < maxIterations) {
    iterations++;
    let matched = false;

    // Check for code blocks first (they take precedence)
    const codeBlockMatch = markdown
      .slice(currentIndex)
      .match(/^```(\w*)\n([\s\S]*?)```/);
    if (codeBlockMatch && codeBlockMatch[0]) {
      const [fullMatch, , code] = codeBlockMatch;
      segments.push({
        type: "codeblock",
        text: code || "",
        raw: fullMatch,
        length: (code || "").length,
      });
      currentIndex += fullMatch.length;
      matched = true;
      continue;
    }

    // Check for inline code
    const inlineCodeMatch = markdown.slice(currentIndex).match(/^`([^`]+)`/);
    if (inlineCodeMatch && inlineCodeMatch[0]) {
      const [fullMatch, code] = inlineCodeMatch;
      segments.push({
        type: "code",
        text: code || "",
        raw: fullMatch,
        length: (code || "").length,
      });
      currentIndex += fullMatch.length;
      matched = true;
      continue;
    }

    // Check for links
    const linkMatch = markdown
      .slice(currentIndex)
      .match(/^\[([^\]]+)\]\(([^)]+)\)/);
    if (linkMatch && linkMatch[0]) {
      const [fullMatch, text] = linkMatch;
      segments.push({
        type: "link",
        text: text || "",
        raw: fullMatch,
        length: (text || "").length,
      });
      currentIndex += fullMatch.length;
      matched = true;
      continue;
    }

    // Check for bold
    const boldMatch = markdown
      .slice(currentIndex)
      .match(/^(\*\*|__)([^*_\n]*?)\1/);
    if (boldMatch && boldMatch[0]) {
      const [fullMatch, , text] = boldMatch;
      segments.push({
        type: "bold",
        text: text || "",
        raw: fullMatch,
        length: (text || "").length,
      });
      currentIndex += fullMatch.length;
      matched = true;
      continue;
    }

    // Check for italic
    const italicMatch = markdown
      .slice(currentIndex)
      .match(/^(\*|_)([^*_\n]+?)\1(?!\*|_)/);
    if (italicMatch && italicMatch[0]) {
      const [fullMatch, , text] = italicMatch;
      segments.push({
        type: "italic",
        text: text || "",
        raw: fullMatch,
        length: (text || "").length,
      });
      currentIndex += fullMatch.length;
      matched = true;
      continue;
    }

    // If no matches were found, handle regular text
    if (!matched) {
      let nextSpecialChar = markdown.slice(currentIndex).search(/[`\[*_]/);
      if (nextSpecialChar === -1) {
        // No more special characters, add the rest as text
        const text = markdown.slice(currentIndex);
        if (text) {
          segments.push({
            type: "text",
            text: text,
            raw: text,
            length: text.length,
          });
        }
        break;
      } else {
        // Add the text up to the next special character
        const text = markdown.slice(
          currentIndex,
          currentIndex + nextSpecialChar
        );
        if (text) {
          segments.push({
            type: "text",
            text: text,
            raw: text,
            length: text.length,
          });
        }
        currentIndex += nextSpecialChar;
      }
    }
  }

  return segments;
}

export function getMarkdownForSelection(
  content: string,
  selectedText: string
): string {
  const segments = parseMarkdownToSegments(content);

  // Build plain text and create mapping to markdown segments
  let plainText = "";
  const markdownPieces: string[] = [];
  let currentPlainIndex = 0;

  segments.forEach((segment) => {
    plainText += segment.text;
    markdownPieces.push(segment.raw);
    currentPlainIndex += segment.length;
  });

  // Find the selection in the plain text
  const startIndex = plainText.indexOf(selectedText);
  if (startIndex === -1) {
    return selectedText;
  }

  const endIndex = startIndex + selectedText.length;

  // Find which segments the selection spans
  let currentIndex = 0;
  let result = "";
  let selectionStart = startIndex;
  let selectionEnd = endIndex;

  segments.forEach((segment) => {
    const segmentStart = currentIndex;
    const segmentEnd = segmentStart + segment.length;

    // Check if this segment overlaps with the selection
    if (segmentEnd > selectionStart && segmentStart < selectionEnd) {
      // Calculate how much of this segment to include
      const overlapStart = Math.max(0, selectionStart - segmentStart);
      const overlapEnd = Math.min(segment.length, selectionEnd - segmentStart);

      if (segment.type === "text") {
        const textPortion = segment.text.slice(overlapStart, overlapEnd);
        result += textPortion;
      } else {
        // For markdown elements, wrap just the selected portion with the appropriate markdown
        const selectedPortion = segment.text.slice(overlapStart, overlapEnd);

        switch (segment.type) {
          case "bold":
            result += `**${selectedPortion}**`;
            break;
          case "italic":
            result += `*${selectedPortion}*`;
            break;
          case "code":
            result += `\`${selectedPortion}\``;
            break;
          case "link":
            // For links, we need to preserve the URL if it exists in the raw markdown
            const urlMatch = segment.raw.match(/\]\((.*?)\)/);
            const url = urlMatch ? urlMatch[1] : "";
            result += `[${selectedPortion}](${url})`;
            break;
          case "codeblock":
            result += `\`\`\`\n${selectedPortion}\n\`\`\``;
            break;
          default:
            result += selectedPortion;
        }
      }
    }

    currentIndex += segment.length;
  });

  return result;
}
