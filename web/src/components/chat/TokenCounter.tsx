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
  
  // Calculate total billed tokens
  const totalBilledTokens = sessionUsage.billedPromptTokens + sessionUsage.billedCompletionTokens + sessionUsage.billedReasoningTokens;

  return (
    <TooltipProvider>
      <Tooltip delayDuration={0}>
        <TooltipTrigger asChild>
          <div className="relative w-32 h-5 bg-neutral-200 dark:bg-neutral-600 rounded-full overflow-hidden shadow-sm">
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
        <TooltipContent className="text-xs max-w-xs bg-white dark:bg-neutral-800 text-neutral-900 dark:text-neutral-100">
          <div className="space-y-3">
            <div className="font-medium text-center">Conversation Token Usage</div>
            
            <div>
              <div className="text-neutral-700 dark:text-neutral-200 font-medium mb-2">Billed Tokens</div>
              <table className="w-full text-xs">
                <tbody>
                  <tr>
                    <td className="text-neutral-500 dark:text-neutral-300">Prompt:</td>
                    <td className="text-right font-mono">{sessionUsage.billedPromptTokens.toLocaleString()}</td>
                  </tr>
                  <tr>
                    <td className="text-neutral-500 dark:text-neutral-300">Completion:</td>
                    <td className="text-right font-mono">{sessionUsage.billedCompletionTokens.toLocaleString()}</td>
                  </tr>
                  {sessionUsage.billedReasoningTokens > 0 ? (
                    <tr>
                      <td className="text-neutral-500 dark:text-neutral-300">Reasoning:</td>
                      <td className="text-right font-mono">{sessionUsage.billedReasoningTokens.toLocaleString()}</td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>

            <div>
              <div className="text-neutral-700 dark:text-neutral-200 font-medium mb-2">Context Usage</div>
              <table className="w-full text-xs">
                <tbody>
                  <tr>
                    <td className="text-neutral-500 dark:text-neutral-300">Current:</td>
                    <td className="text-right font-mono">{sessionUsage.contextTotalTokens.toLocaleString()}</td>
                  </tr>
                  <tr>
                    <td className="text-neutral-500 dark:text-neutral-300">Max:</td>
                    <td className="text-right font-mono">{maxTokens.toLocaleString()}</td>
                  </tr>
                  <tr>
                    <td className="text-neutral-500 dark:text-neutral-300">Usage:</td>
                    <td className="text-right font-mono">{tokenPercentage.toFixed(1)}%</td>
                  </tr>
                </tbody>
              </table>
            </div>

            {currentModel && (
              <div className="text-center pt-2 border-t">
                <div className="text-neutral-400 text-[10px]">
                  {getDisplayNameForModel(currentModel.modelName)}
                </div>
              </div>
            )}
          </div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
};