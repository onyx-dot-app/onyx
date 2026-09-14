import { JSX } from "react";

/**
 * Check if a message contains partial thinking tokens (streaming)
 */
function hasPartialThinkingTokens(content: string | JSX.Element): boolean {
  if (typeof content !== "string") return false;

  // Count opening and closing tags
  const thinkOpenCount = (content.match(/<think>/g) || []).length;
  const thinkCloseCount = (content.match(/<\/think>/g) || []).length;
  const thinkingOpenCount = (content.match(/<thinking>/g) || []).length;
  const thinkingCloseCount = (content.match(/<\/thinking>/g) || []).length;

  // Return true if we have any unmatched tags
  return (
    thinkOpenCount > thinkCloseCount || thinkingOpenCount > thinkingCloseCount
  );
}

/**
 * Remove thinking tokens from content
 */
export function removeThinkingTokens(
  content: string | JSX.Element
): string | JSX.Element {
  if (typeof content !== "string") return content;

  // First, remove complete thinking blocks
  let result = content.replace(/<think>[\s\S]*?<\/think>/g, "");
  result = result.replace(/<thinking>[\s\S]*?<\/thinking>/g, "");

  // Handle case where there's an incomplete thinking token at the end
  if (hasPartialThinkingTokens(result)) {
    // Find the last opening tag position
    const lastThinkPos = result.lastIndexOf("<think>");
    const lastThinkingPos = result.lastIndexOf("<thinking>");

    // Use the position of whichever tag appears last
    const startPos = Math.max(lastThinkPos, lastThinkingPos);

    if (startPos >= 0) {
      // Only keep content before the last opening tag
      result = result.substring(0, startPos);
    }
  }

  return result.trim();
}
