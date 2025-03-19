/**
 * Utility functions to handle thinking tokens in AI messages
 */

/**
 * Check if a message contains complete thinking tokens
 */
export function hasCompletedThinkingTokens(content: string | JSX.Element): boolean {
  if (typeof content !== 'string') return false;
  
  return /<think>[\s\S]*?<\/think>/.test(content) || 
         /<thinking>[\s\S]*?<\/thinking>/.test(content);
}

/**
 * Check if a message contains partial thinking tokens (streaming)
 */
export function hasPartialThinkingTokens(content: string | JSX.Element): boolean {
  if (typeof content !== 'string') return false;
  
  // Check for opening tag without closing tag
  const hasOpeningThink = content.includes('<think>');
  const hasClosingThink = content.includes('</think>');
  const hasOpeningThinking = content.includes('<thinking>');
  const hasClosingThinking = content.includes('</thinking>');
  
  // Return true if we have an opening tag with no corresponding closing tag
  // or if we have an opening and closing tag, but the pattern "<think>...</think>" isn't found
  // (which means the closing tag belongs to a different opening tag)
  return (hasOpeningThink && !hasClosingThink) || 
         (hasOpeningThinking && !hasClosingThinking) ||
         (hasOpeningThink && hasClosingThink && !/<think>[\s\S]*?<\/think>/.test(content)) ||
         (hasOpeningThinking && hasClosingThinking && !/<thinking>[\s\S]*?<\/thinking>/.test(content));
}

/**
 * Extract thinking content from a message
 */
export function extractThinkingContent(content: string | JSX.Element): string {
  if (typeof content !== 'string') return '';
  
  // For complete thinking tags, extract the whole section
  const completeThinkRegex = /<think>[\s\S]*?<\/think>/;
  const completeThinkingRegex = /<thinking>[\s\S]*?<\/thinking>/;
  
  const thinkMatch = content.match(completeThinkRegex);
  const thinkingMatch = content.match(completeThinkingRegex);
  
  if (thinkMatch) {
    return thinkMatch[0];
  }
  
  if (thinkingMatch) {
    return thinkingMatch[0];
  }
  
  // For partial thinking tokens (streaming)
  if (hasPartialThinkingTokens(content)) {
    // Find the opening tag position
    const thinkPos = content.indexOf('<think>');
    const thinkingPos = content.indexOf('<thinking>');
    
    let startPos = -1;
    if (thinkPos >= 0) {
      startPos = thinkPos;
    } else if (thinkingPos >= 0) {
      startPos = thinkingPos;
    }
    
    if (startPos >= 0) {
      // Extract everything from the opening tag to the end
      return content.substring(startPos);
    }
  }
  
  return '';
}

/**
 * Check if thinking tokens are complete
 */
export function isThinkingComplete(content: string | JSX.Element): boolean {
  if (typeof content !== 'string') return true;
  
  // Check if content has the closing tag
  const hasClosingThink = content.includes('</think>');
  const hasClosingThinking = content.includes('</thinking>');
  
  // Also check if we have complete patterns to ensure the closing tag matches the opening tag
  const hasCompleteThink = /<think>[\s\S]*?<\/think>/.test(content);
  const hasCompleteThinking = /<thinking>[\s\S]*?<\/thinking>/.test(content);
  
  return (hasClosingThink && hasCompleteThink) || (hasClosingThinking && hasCompleteThinking);
}

/**
 * Remove thinking tokens from content
 */
export function removeThinkingTokens(content: string | JSX.Element): string | JSX.Element {
  if (typeof content !== 'string') return content;
  
  // First, remove complete thinking blocks
  let result = content.replace(/<think>[\s\S]*?<\/think>/g, '');
  result = result.replace(/<thinking>[\s\S]*?<\/thinking>/g, '');
  
  // Handle case where there's an incomplete thinking token at the end
  if (hasPartialThinkingTokens(result)) {
    const thinkPos = result.indexOf('<think>');
    const thinkingPos = result.indexOf('<thinking>');
    
    // Find the position of the first opening tag
    let startPos = -1;
    if (thinkPos >= 0) {
      startPos = thinkPos;
    } else if (thinkingPos >= 0) {
      startPos = thinkingPos;
    }
    
    if (startPos >= 0) {
      // Only keep content before the opening tag
      result = result.substring(0, startPos);
    }
  }
  
  return result.trim();
}

/**
 * Clean the extracted thinking content (remove tags)
 */
export function cleanThinkingContent(thinkingContent: string): string {
  if (!thinkingContent) return '';
  
  return thinkingContent
    .replace(/<think>|<\/think>|<thinking>|<\/thinking>/g, '')
    .trim();
} 