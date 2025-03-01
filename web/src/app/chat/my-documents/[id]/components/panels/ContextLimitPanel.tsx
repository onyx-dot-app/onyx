import React, { useState } from "react";
import { Info, ChevronRight, ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { LLMModelDescriptor } from "@/app/admin/configuration/llm/interfaces";
import { ModelSelector } from "./ModelSelector";
import { useChatContext } from "@/components/context/ChatContext";
import { getDisplayNameForModel } from "@/lib/hooks";

interface ContextLimitPanelProps {
  isOpen: boolean;
  onToggle: () => void;
  totalTokens: number;
}

export function ContextLimitPanel({
  isOpen,
  onToggle,
  totalTokens,
}: ContextLimitPanelProps) {
  const { llmProviders } = useChatContext();
  const modelDescriptors = llmProviders.flatMap((provider) =>
    Object.entries(provider.model_token_limits ?? {}).map(
      ([modelName, maxTokens]) => ({
        modelName,
        provider: provider.provider,
        maxTokens,
      })
    )
  );

  return (
    <div className="p-4 border-b border-neutral-300 dark:border-neutral-600">
      <div
        className="flex items-center justify-between text-neutral-900 dark:text-neutral-300"
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
        <div className="mt-2 mb-3 text-neutral-600 dark:text-neutral-400 text-sm">
          <p className="mb-2">
            This panel shows how much of each model&apos;s context window is
            used by the documents in this group.
          </p>
          <p>
            Total tokens in this group:{" "}
            <span className="font-medium">{totalTokens.toLocaleString()}</span>
          </p>
        </div>
      )}

      {isOpen && (
        <div className="mt-1 pt-1 border-t border-neutral-600 text-neutral-600 dark:text-neutral-400 text-sm font-normal default-scrollbar leading-tight max-h-60 overflow-y-auto pr-1">
          {modelDescriptors.map((model, index) => {
            const tokenPercentage = (totalTokens / model.maxTokens) * 100;
            return (
              <div
                key={`${model.provider}-${model.modelName}`}
                className="mb-3"
              >
                <div className="mb-1 flex justify-between">
                  <span>{getDisplayNameForModel(model.modelName)}</span>
                  <span>{model.maxTokens}</span>
                </div>
                <div className="w-full bg-neutral-200 dark:bg-neutral-700 rounded-full h-2.5">
                  <div
                    className={`h-2.5 rounded-full ${
                      tokenPercentage > 100 ? "bg-red-600" : "bg-blue-600"
                    }`}
                    style={{ width: `${Math.min(tokenPercentage, 100)}%` }}
                  ></div>
                </div>
                {tokenPercentage > 100 && (
                  <div className="mt-1 text-xs text-red-500 dark:text-red-400">
                    Capacity exceeded
                  </div>
                )}
              </div>
            );
          })}
          {modelDescriptors.length === 0 && (
            <div className="text-xs text-neutral-500 dark:text-neutral-400">
              No models available
            </div>
          )}
        </div>
      )}
    </div>
  );
}
