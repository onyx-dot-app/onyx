import React from 'react';
import { SessionTokenUsage } from '@/hooks/useTokenCounter';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { getDisplayNameForModel } from "@/lib/hooks";

interface TokenCounterProps {
  sessionUsage: SessionTokenUsage;
  currentModel?: {
    modelName: string;
    maxTokens: number;
  };
}

export const TokenCounter: React.FC<TokenCounterProps> = ({ 
  sessionUsage, 
  currentModel 
}) => {
  if (sessionUsage.contextTotalTokens === 0) {
    return null;
  }

  const formatNumber = (num: number) => {
    if (num >= 1000000) {
      return (num / 1000000).toFixed(1) + 'M';
    }
    if (num >= 1000) {
      return (num / 1000).toFixed(1) + 'k';
    }
    return num.toString();
  };

  // Calculate percentage based on context tokens (context window usage)
  const maxTokens = currentModel?.maxTokens || 200000; // Default fallback
  const tokenPercentage = (sessionUsage.contextTotalTokens / maxTokens) * 100;

  return (
    <TooltipProvider>
      <Tooltip delayDuration={0}>
        <TooltipTrigger asChild>
          <div className="relative w-32 h-5 bg-neutral-200 dark:bg-neutral-700 rounded-full overflow-hidden">
            <div
              className={`absolute top-0 left-0 h-full rounded-full ${
                tokenPercentage >= 100
                  ? "bg-red-500 dark:bg-red-600"
                  : tokenPercentage >= 80
                  ? "bg-yellow-500 dark:bg-yellow-600"
                  : "bg-green-500 dark:bg-green-600"
              }`}
              style={{
                width: `${Math.min(tokenPercentage, 100)}%`,
              }}
            ></div>
            {/* Text overlay */}
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="flex items-center gap-1 text-xs font-medium whitespace-nowrap">
                <span className="text-neutral-700 dark:text-neutral-200 drop-shadow-sm">
                  {formatNumber(sessionUsage.contextTotalTokens)} / {formatNumber(maxTokens)}
                </span>
                <span className="text-neutral-500 dark:text-neutral-300 text-[10px] drop-shadow-sm">
                  tokens
                </span>
              </div>
            </div>
          </div>
        </TooltipTrigger>
        <TooltipContent className="text-xs max-w-xs">
          <div className="space-y-1">
            <div className="font-medium">Conversation Token Usage</div>
            <div className="space-y-1">
              <div className="text-neutral-600 dark:text-neutral-300 font-medium">Billed Tokens:</div>
              <div>Prompt: {sessionUsage.billedPromptTokens.toLocaleString()}</div>
              <div>Completion: {sessionUsage.billedCompletionTokens.toLocaleString()}</div>
              {sessionUsage.billedReasoningTokens > 0 && (
                <div>Reasoning: {sessionUsage.billedReasoningTokens.toLocaleString()}</div>
              )}
            </div>
            <div className="border-t pt-1 mt-2">
              <div className="text-neutral-600 dark:text-neutral-300 font-medium">Context Usage:</div>
              <div>Current: {formatNumber(sessionUsage.contextTotalTokens)}</div>
              <div>Max: {formatNumber(maxTokens)} ({tokenPercentage.toFixed(1)}% used)</div>
            </div>
            {currentModel && (
              <div className="text-neutral-400 mt-1">
                Model: {getDisplayNameForModel(currentModel.modelName)}
              </div>
            )}
          </div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
};