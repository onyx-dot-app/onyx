/**
 * Utility functions to handle thinking tokens in AI messages
 */

/**
 * Check if a message contains complete thinking tokens
 */
export function hasCompletedThinkingTokens(
  content: string | JSX.Element
): boolean {
  if (typeof content !== "string") return false;

  return (
    /<think>[\s\S]*?<\/think>/.test(content) ||
    /<thinking>[\s\S]*?<\/thinking>/.test(content)
  );
}

/**
 * Check if a message contains partial thinking tokens (streaming)
 */
export function hasPartialThinkingTokens(
  content: string | JSX.Element
): boolean {
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
 * Extract thinking content from a message
 */
export function extractThinkingContent(content: string | JSX.Element): string {
  if (typeof content !== "string") return "";

  // For complete thinking tags, extract all sections
  const completeThinkRegex = /<think>[\s\S]*?<\/think>/g;
  const completeThinkingRegex = /<thinking>[\s\S]*?<\/thinking>/g;

  const thinkMatches = Array.from(content.matchAll(completeThinkRegex));
  const thinkingMatches = Array.from(content.matchAll(completeThinkingRegex));

  if (thinkMatches.length > 0 || thinkingMatches.length > 0) {
    // Combine all matches and sort by their position in the original string
    const allMatches = [...thinkMatches, ...thinkingMatches].sort(
      (a, b) => (a.index || 0) - (b.index || 0)
    );
    return allMatches.map((match) => match[0]).join("\n");
  }

  // For partial thinking tokens (streaming)
  if (hasPartialThinkingTokens(content)) {
    // Find the last opening tag position
    const lastThinkPos = content.lastIndexOf("<think>");
    const lastThinkingPos = content.lastIndexOf("<thinking>");

    // Use the position of whichever tag appears last
    const startPos = Math.max(lastThinkPos, lastThinkingPos);

    if (startPos >= 0) {
      // Extract everything from the last opening tag to the end
      return content.substring(startPos);
    }
  }

  return "";
}

/**
 * Check if thinking tokens are complete
 */
export function isThinkingComplete(content: string | JSX.Element): boolean {
  if (typeof content !== "string") return false;

  // Count opening and closing tags
  const thinkOpenCount = (content.match(/<think>/g) || []).length;
  const thinkCloseCount = (content.match(/<\/think>/g) || []).length;
  const thinkingOpenCount = (content.match(/<thinking>/g) || []).length;
  const thinkingCloseCount = (content.match(/<\/thinking>/g) || []).length;

  // All tags must be matched
  return (
    thinkOpenCount === thinkCloseCount &&
    thinkingOpenCount === thinkingCloseCount
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

// /**
//  * Clean the extracted thinking content (remove tags)
//  */
export function cleanThinkingContent(thinkingContent: string): string {
  if (!thinkingContent) return "";

  return thinkingContent
    .replace(/<think>|<\/think>|<thinking>|<\/thinking>/g, "")
    .trim();
}
