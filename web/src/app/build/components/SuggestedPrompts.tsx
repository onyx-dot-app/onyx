"use client";

import { cn } from "@/lib/utils";
import {
  getPromptsForPersona,
  UserPersona,
} from "@/app/build/constants/exampleBuildPrompts";

interface SuggestedPromptsProps {
  persona?: UserPersona;
  onPromptClick: (promptText: string) => void;
}

/**
 * SuggestedPrompts - Displays clickable prompt suggestions in a 2x2 grid
 *
 * Shows a 2x2 grid of example prompts based on user persona.
 * Each prompt has summary text on top and a cropped image below it.
 * Clicking a prompt triggers the onPromptClick callback.
 */
export default function SuggestedPrompts({
  persona = "default",
  onPromptClick,
}: SuggestedPromptsProps) {
  const prompts = getPromptsForPersona(persona);
  // Take only the first 4 prompts for the 2x2 grid
  const gridPrompts = prompts.slice(0, 4);

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
            "focus:outline-none focus:ring-2 focus:ring-action-link-01 focus:ring-offset-2"
          )}
        >
          {/* Summary text */}
          <span className="text-sm text-text-04 text-center leading-tight">
            {prompt.summary}
          </span>
          {/* Image resized to cut in half height (4:1 aspect ratio) */}
          {prompt.image && (
            <div className="w-full aspect-[4/1] rounded-08 overflow-hidden bg-background-neutral-01">
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
