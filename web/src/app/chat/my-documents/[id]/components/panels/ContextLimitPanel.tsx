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
    <div className="p-4 border-b border-[#d9d9d0]">
      <div className="flex items-center justify-between" onClick={onToggle}>
        <div className="flex items-center">
          <Info className="w-5 h-4 mr-3 text-[#13343a]" />
          <span className="text-[#13343a] text-sm font-medium leading-tight">
            Context Limit
          </span>
        </div>

        <Button variant="ghost" size="sm" className="w-6 h-6 p-0 rounded-full">
          {isOpen ? (
            <ChevronDown className="w-[15px] h-3 text-[#13343a]" />
          ) : (
            <ChevronRight className="w-[15px] h-3 text-[#13343a]" />
          )}
        </Button>
      </div>

      {isOpen && (
        <div className="mt-2 text-[#64645e] text-sm font-normal leading-tight">
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
          <div className="w-full bg-gray-200 rounded-full h-2.5">
            <div
              className={`h-2.5 rounded-full ${
                tokenPercentage > 100 ? "bg-green-600" : "bg-blue-600"
              }`}
              style={{ width: `${Math.min(tokenPercentage, 100)}%` }}
            ></div>
          </div>
          {tokenPercentage > 100 && (
            <div className="mt-1 text-xs text-text-500">
              Capacity exceeded. Search will be performed over content.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
