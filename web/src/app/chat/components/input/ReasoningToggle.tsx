import React, { useState, useEffect, useRef } from "react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { BiBrain } from "react-icons/bi";
import { FiCheck } from "react-icons/fi";
import { LlmManager } from "@/lib/hooks";
import { modelSupportsReasoning } from "@/lib/llm/utils";
import { LLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import { cn } from "@/lib/utils";
import { ChatInputOption } from "./ChatInputOption";
import { IconProps } from "@/components/icons/icons";

interface ReasoningToggleProps {
  llmManager: LlmManager;
  llmProviders: LLMProviderDescriptor[];
}

type ReasoningLevel = "low" | "medium" | "high";

const REASONING_LEVELS: {
  value: ReasoningLevel;
  label: string;
  abbrev: string;
  description: string;
  color: string;
}[] = [
  {
    value: "low",
    label: "Low",
    abbrev: "low",
    description: "Quick reasoning with minimal thinking",
    color: "text-green-500 dark:text-green-400",
  },
  {
    value: "medium",
    label: "Medium",
    abbrev: "med",
    description: "Balanced reasoning depth",
    color: "text-yellow-500 dark:text-yellow-400",
  },
  {
    value: "high",
    label: "High",
    abbrev: "high",
    description: "Deep reasoning with extensive thinking",
    color: "text-red-500 dark:text-red-400",
  },
];

export default function ReasoningToggle({
  llmManager,
  llmProviders,
}: ReasoningToggleProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [showLabel, setShowLabel] = useState(false);
  const labelTimerRef = useRef<NodeJS.Timeout | null>(null);
  
  const supportsReasoning = modelSupportsReasoning(
    llmProviders,
    llmManager.currentLlm.modelName,
    llmManager.currentLlm.name
  );

  useEffect(() => {
    return () => {
      if (labelTimerRef.current) {
        clearTimeout(labelTimerRef.current);
      }
    };
  }, []);

  if (!supportsReasoning) {
    return null;
  }

  const currentLevel = REASONING_LEVELS.find(l => l.value === llmManager.reasoningLevel);
  const iconColor = currentLevel?.color || "text-gray-500";

  const BrainIcon = ({ size = 16, className }: IconProps) => (
    <BiBrain size={size} className={`${iconColor} ${className || ""}`} />
  );

  const handleLevelSelect = (level: ReasoningLevel) => {
    llmManager.updateReasoningLevel(level);
    setIsOpen(false);
    setShowLabel(true);
    if (labelTimerRef.current) {
      clearTimeout(labelTimerRef.current);
    }
    labelTimerRef.current = setTimeout(() => {
      setShowLabel(false);
    }, 2000);
  };

  return (
    <Popover open={isOpen} onOpenChange={setIsOpen}>
      <PopoverTrigger asChild>
        <button
          className="dark:text-[#fff] text-[#000] focus:outline-none"
          aria-label={`Reasoning Level: ${currentLevel?.label}`}
          onClick={(e) => {
            e.preventDefault();
            setIsOpen((prev) => !prev);
          }}
        >
          <ChatInputOption
            Icon={BrainIcon}
            tooltipContent={`${currentLevel?.label || ""} reasoning`}
            flexPriority="stiff"
            minimize
            toggle={false}
            name={showLabel ? `${currentLevel?.label} Reasoning` : undefined}
            active={showLabel || isOpen}
          />
        </button>
      </PopoverTrigger>
      <PopoverContent
        side="top"
        align="center"
        className="w-56 p-2 bg-background border border-gray-200 dark:border-gray-700 rounded-md shadow-lg"
      >
        <div className="space-y-0.5">
          <div className="text-xs font-medium px-2 pb-1 text-gray-500 dark:text-gray-400">Reasoning Level</div>
          {REASONING_LEVELS.map((level) => (
            <button
              key={level.value}
              onClick={() => handleLevelSelect(level.value)}
              className={cn(
                "w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-left transition-colors",
                llmManager.reasoningLevel === level.value
                  ? "bg-primary/10 text-primary font-medium"
                  : "hover:bg-background-chat-hover"
              )}
            >
              <div className="flex-shrink-0">
                <BiBrain size={14} className={level.color} />
              </div>
              <div className="flex-grow">
                <div className="font-medium text-sm leading-tight">{level.label}</div>
                <div className="text-xs text-gray-500 dark:text-gray-400 leading-tight">
                  {level.description}
                </div>
              </div>
              {llmManager.reasoningLevel === level.value && (
                <FiCheck size={14} className="flex-shrink-0" />
              )}
            </button>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
}