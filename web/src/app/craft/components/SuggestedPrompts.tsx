"use client";

import { useState } from "react";
import { cn } from "@opal/utils";
import {
  exampleBuildPrompts,
  BuildPrompt,
} from "@/app/craft/constants/exampleBuildPrompts";

interface SuggestedPromptsProps {
  onPromptClick: (promptText: string) => void;
}

/**
 * Shuffles an array using Fisher-Yates algorithm
 */
function shuffleArray<T>(array: T[]): T[] {
  const shuffled = [...array];
  for (let i = shuffled.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    const temp = shuffled[i]!;
    shuffled[i] = shuffled[j]!;
    shuffled[j] = temp;
  }
  return shuffled;
}

/**
 * Randomly selects 4 prompts from the available prompts
 */
function selectRandomPrompts(prompts: BuildPrompt[]): BuildPrompt[] {
  const shuffled = shuffleArray(prompts);
  return shuffled.slice(0, 4);
}

/**
 * SuggestedPrompts - Displays clickable prompt suggestions in a 2x2 grid
 *
 * Shows a 2x2 grid of example prompts.
 * Each prompt has summary text on top and a cropped image below it.
 * Clicking a prompt triggers the onPromptClick callback.
 * Randomly selects 4 prompts, shuffled on every component mount (when user returns).
 */
export default function SuggestedPrompts({
  onPromptClick,
}: SuggestedPromptsProps) {
  // Randomly select 4 prompts - shuffles on mount (when user returns)
  const [gridPrompts] = useState<BuildPrompt[]>(() =>
    selectRandomPrompts(exampleBuildPrompts)
  );

  return (
    <div className="mt-4 w-full grid grid-cols-2 gap-4">
      {gridPrompts.map((prompt) => (
        <button
          key={prompt.id}
          onClick={() => onPromptClick(prompt.fullText)}
          className={cn(
            "flex flex-col items-center gap-2",
            "p-4 rounded-12",
            "bg-background-neutral-00 border border-border-01",
            "hover:bg-background-neutral-01 hover:border-border-02",
            "transition-all duration-200",
            "cursor-pointer",
            "focus:outline-hidden focus:ring-2 focus:ring-action-link-01 focus:ring-offset-2"
          )}
        >
          {/* Summary text */}
          <span className="text-sm text-text-04 text-center leading-tight">
            {prompt.summary}
          </span>
          {/* Image resized to cut in half height (4:1 aspect ratio) */}
          {prompt.image && (
            <div className="w-full aspect-3/1 rounded-08 overflow-hidden bg-background-neutral-01">
              <img
                src={prompt.image}
                alt={prompt.summary}
                className="w-full h-full object-cover object-top"
              />
            </div>
          )}
        </button>
      ))}
    </div>
  );
}
