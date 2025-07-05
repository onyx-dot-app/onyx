import { useState, useCallback } from 'react';

export interface TokenUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  completion_tokens_details?: {
    reasoning_tokens?: number;
  };
}

export interface SessionTokenUsage {
  // Billed tokens - incremental sum of each message (what you actually pay for)
  billedPromptTokens: number;
  billedCompletionTokens: number;
  billedReasoningTokens: number;
  
  // Context tokens - current total context size (context window usage)
  contextTotalTokens: number;
  
  messageCount: number;
}

export const useTokenCounter = () => {
  const [sessionUsage, setSessionUsage] = useState<SessionTokenUsage>({
    billedPromptTokens: 0,
    billedCompletionTokens: 0,
    billedReasoningTokens: 0,
    contextTotalTokens: 0,
    messageCount: 0,
  });

  const updateTokenUsage = useCallback((usage: TokenUsage) => {
    setSessionUsage(prev => {
      // For incremental billing:
      // - First message: all prompt tokens are new
      // - Subsequent messages: current prompt tokens - previous total context (since previous total = previous prompt + previous completion)
      const incrementalPromptTokens = prev.messageCount === 0 
        ? usage.prompt_tokens  // First message: all prompt tokens are new
        : usage.prompt_tokens - prev.contextTotalTokens; // Subsequent: new prompt content only
      
      return {
        // Billed tokens - add incremental costs
        billedPromptTokens: prev.billedPromptTokens + Math.max(0, incrementalPromptTokens),
        billedCompletionTokens: prev.billedCompletionTokens + usage.completion_tokens,
        billedReasoningTokens: prev.billedReasoningTokens + (usage.completion_tokens_details?.reasoning_tokens || 0),
        
        // Context tokens - current total context size  
        contextTotalTokens: usage.total_tokens,
        
        messageCount: prev.messageCount + 1,
      };
    });
  }, []);

  const resetTokenCounter = useCallback(() => {
    setSessionUsage({
      billedPromptTokens: 0,
      billedCompletionTokens: 0,
      billedReasoningTokens: 0,
      contextTotalTokens: 0,
      messageCount: 0,
    });
  }, []);

  return {
    sessionUsage,
    updateTokenUsage,
    resetTokenCounter,
  };
};