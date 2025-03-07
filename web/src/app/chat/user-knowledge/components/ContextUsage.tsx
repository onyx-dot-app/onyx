import React from "react";

interface ContextUsageProps {
  totalTokens: number;
  maxTokens: number;
  modelName?: string;
  compact?: boolean;
}

export const ContextUsage: React.FC<ContextUsageProps> = ({
  totalTokens,
  maxTokens,
  modelName,
  compact = false,
}) => {
  const tokenPercentage = Math.round((totalTokens / maxTokens) * 100);

  return (
    <div className={`flex ${compact ? "items-center gap-2" : "flex-col"}`}>
      {modelName && !compact && (
        <span className="text-xs text-neutral-500 dark:text-neutral-400 mb-1">
          Context usage for {modelName}
        </span>
      )}

      <div
        className={`flex items-center gap-2 ${
          !compact
            ? "px-3 py-1.5 bg-neutral-100 dark:bg-neutral-800 rounded-lg shadow-sm"
            : ""
        }`}
      >
        <div className="h-2 w-16 bg-neutral-200 dark:bg-neutral-700 rounded-full overflow-hidden">
          <div
            className={`h-full transition-all duration-300 ${
              tokenPercentage > 75
                ? "bg-red-500"
                : tokenPercentage > 50
                  ? "bg-amber-500"
                  : "bg-emerald-500"
            }`}
            style={{ width: `${Math.min(tokenPercentage, 100)}%` }}
          />
        </div>
        <span className="text-xs font-medium text-neutral-700 dark:text-neutral-300">
          {totalTokens.toLocaleString()} / {maxTokens.toLocaleString()} tokens
        </span>
      </div>
    </div>
  );
};
