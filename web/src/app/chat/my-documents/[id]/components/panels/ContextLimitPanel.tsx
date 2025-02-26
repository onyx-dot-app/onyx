import React from "react";
import { Info, ChevronRight, ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { LLMModelDescriptor } from "@/app/admin/configuration/llm/interfaces";
import { ModelSelector } from "./ModelSelector";

interface ContextLimitPanelProps {
  isOpen: boolean;
  onToggle: () => void;
  tokenPercentage: number;
  totalTokens: number;
  maxTokens: number;
  selectedModel: LLMModelDescriptor;
  modelDescriptors: LLMModelDescriptor[];
  onSelectModel: (model: LLMModelDescriptor) => void;
}

export function ContextLimitPanel({
  isOpen,
  onToggle,
  tokenPercentage,
  totalTokens,
  maxTokens,
  selectedModel,
  modelDescriptors,
  onSelectModel,
}: ContextLimitPanelProps) {
  return (
    <div className="p-4 border-b border-neutral-200 dark:border-neutral-700">
      <div
        className="flex items-center justify-between text-[#13343a] dark:text-neutral-300"
        onClick={onToggle}
      >
        <div className="flex items-center">
          <Info className="w-5 h-4 mr-3" />
          <span className="text-sm font-medium leading-tight">
            Context Limit
          </span>
        </div>

        <Button variant="ghost" size="sm" className="w-6 h-6 p-0 rounded-full">
          {isOpen ? (
            <ChevronDown className="w-[15px] h-3" />
          ) : (
            <ChevronRight className="w-[15px] h-3" />
          )}
        </Button>
      </div>

      {isOpen && (
        <div className="mt-2 text-neutral-600 dark:text-neutral-400 text-sm font-normal leading-tight">
          <div className="mb-2">
            <ModelSelector
              models={modelDescriptors}
              selectedModel={selectedModel}
              onSelectModel={onSelectModel}
            />
          </div>
          <div className="mb-1">
            Tokens: {totalTokens} / {maxTokens}
          </div>
          <div className="w-full bg-neutral-200 dark:bg-neutral-700 rounded-full h-2.5">
            <div
              className={`h-2.5 rounded-full ${
                tokenPercentage > 100 ? "bg-green-600" : "bg-blue-600"
              }`}
              style={{ width: `${Math.min(tokenPercentage, 100)}%` }}
            ></div>
          </div>
          {tokenPercentage > 100 && (
            <div className="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
              Capacity exceeded. Search will be performed over content.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
