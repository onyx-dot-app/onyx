"use client";

import { useState, useMemo } from "react";
import { LlmDescriptor } from "@/lib/hooks";
import { getProviderIcon } from "@/app/admin/configuration/llm/utils";
import { cn } from "@/lib/utils";

export interface ModelResponse {
  model: LlmDescriptor;
  // For now, we'll just use the model info. Content is handled by parent.
  // In future: could include per-model packets, citations, etc.
}

interface ModelResponseTabsProps {
  modelResponses: ModelResponse[];
  activeIndex: number;
  onTabChange: (index: number) => void;
}

export function ModelResponseTabs({
  modelResponses,
  activeIndex,
  onTabChange,
}: ModelResponseTabsProps) {
  if (modelResponses.length <= 1) {
    return null;
  }

  return (
    <div className="flex items-center gap-1 mb-3 pb-2 border-b border-border-01">
      {modelResponses.map((response, index) => {
        const isActive = index === activeIndex;
        const Icon = getProviderIcon(
          response.model.provider,
          response.model.modelName
        );

        return (
          <button
            key={`${response.model.provider}-${response.model.modelName}-${index}`}
            onClick={() => onTabChange(index)}
            className={cn(
              "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm transition-colors",
              isActive
                ? "bg-background-emphasis text-text-01 font-medium"
                : "text-text-03 hover:bg-background-hover hover:text-text-02"
            )}
          >
            <Icon size={16} />
            <span className="max-w-[120px] truncate">
              {response.model.modelName || response.model.provider}
            </span>
            {isActive && (
              <span className="w-1.5 h-1.5 rounded-full bg-action-link-01" />
            )}
          </button>
        );
      })}
    </div>
  );
}

// Hook to manage multi-model response state
export function useModelResponses(modelResponses?: ModelResponse[]) {
  const [activeIndex, setActiveIndex] = useState(0);

  // Reset active index if it's out of bounds
  const safeActiveIndex = useMemo(() => {
    if (!modelResponses || modelResponses.length === 0) return 0;
    return Math.min(activeIndex, modelResponses.length - 1);
  }, [activeIndex, modelResponses]);

  const hasMultipleResponses = (modelResponses?.length ?? 0) > 1;

  const activeResponse = modelResponses?.[safeActiveIndex];

  return {
    activeIndex: safeActiveIndex,
    setActiveIndex,
    hasMultipleResponses,
    activeResponse,
  };
}
