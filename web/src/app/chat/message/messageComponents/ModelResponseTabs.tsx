"use client";

import { useState, useMemo, useEffect, useRef } from "react";
import { LlmDescriptor } from "@/lib/hooks";
import { getProviderIcon } from "@/app/admin/configuration/llm/utils";
import { cn } from "@/lib/utils";
import { isStreamingComplete } from "@/app/chat/services/packetUtils";
import { FiCheck } from "react-icons/fi";

import { Message } from "@/app/chat/interfaces";

export interface ModelResponse {
  model: LlmDescriptor;
  // The actual message data for this model's response
  message?: Message;
}

interface ModelResponseTabsProps {
  modelResponses: ModelResponse[];
  activeIndex: number;
  onTabChange: (index: number) => void;
}

// Streaming indicator component - pulsing dot animation
function StreamingIndicator() {
  return (
    <span className="relative flex h-2 w-2">
      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75" />
      <span className="relative inline-flex rounded-full h-2 w-2 bg-amber-500" />
    </span>
  );
}

// Completion indicator component - checkmark
function CompletedIndicator() {
  return (
    <span className="flex items-center justify-center h-3.5 w-3.5 rounded-full bg-emerald-500/20">
      <FiCheck className="h-2.5 w-2.5 text-emerald-600" strokeWidth={3} />
    </span>
  );
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

        // Determine streaming status for this model's response
        const packets = response.message?.packets || [];
        const isComplete = isStreamingComplete(packets);
        const hasStartedStreaming = packets.length > 0;

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
            {/* Status indicator: streaming or complete */}
            {hasStartedStreaming && !isComplete && <StreamingIndicator />}
            {isComplete && <CompletedIndicator />}
          </button>
        );
      })}
    </div>
  );
}

// Hook to manage multi-model response state
export function useModelResponses(
  modelResponses?: ModelResponse[],
  latestChildNodeId?: number | null
) {
  // Calculate initial index based on latestChildNodeId
  const initialIndex = useMemo(() => {
    if (!modelResponses || modelResponses.length === 0) return 0;
    if (latestChildNodeId === undefined || latestChildNodeId === null) return 0;

    const index = modelResponses.findIndex(
      (r) => r.message?.nodeId === latestChildNodeId
    );
    return index >= 0 ? index : 0;
  }, [modelResponses, latestChildNodeId]);

  const [activeIndex, setActiveIndex] = useState(initialIndex);

  // Track previous modelResponses length to detect new responses (regeneration)
  const prevLengthRef = useRef(modelResponses?.length ?? 0);

  // Auto-switch to new tab when a response is added (regeneration case)
  // Also sync with latestChildNodeId when it changes (e.g., on load or branch switch)
  useEffect(() => {
    const currentLength = modelResponses?.length ?? 0;

    // If a new response was added, switch to it (regeneration case)
    if (currentLength > prevLengthRef.current && currentLength > 0) {
      setActiveIndex(currentLength - 1);
    }
    // If latestChildNodeId changed (e.g., loading chat), sync to it
    else if (
      latestChildNodeId !== undefined &&
      latestChildNodeId !== null &&
      modelResponses
    ) {
      const targetIndex = modelResponses.findIndex(
        (r) => r.message?.nodeId === latestChildNodeId
      );
      if (targetIndex >= 0 && targetIndex !== activeIndex) {
        setActiveIndex(targetIndex);
      }
    }

    prevLengthRef.current = currentLength;
  }, [modelResponses, latestChildNodeId, activeIndex]);

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
