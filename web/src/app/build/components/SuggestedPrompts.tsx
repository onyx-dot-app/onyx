"use client";

import Button from "@/refresh-components/buttons/Button";
import {
  getPromptsForPersona,
  UserPersona,
} from "@/app/build/constants/exampleBuildPrompts";

interface SuggestedPromptsProps {
  persona?: UserPersona;
  onPromptClick: (promptText: string) => void;
}

/**
 * SuggestedPrompts - Displays clickable prompt suggestions
 *
 * Shows a set of example prompts based on user persona.
 * Clicking a prompt triggers the onPromptClick callback.
 */
export default function SuggestedPrompts({
  persona = "default",
  onPromptClick,
}: SuggestedPromptsProps) {
  const prompts = getPromptsForPersona(persona);

  return (
    <div className="mt-4 flex flex-wrap justify-start gap-y-2">
      {prompts.map((prompt) => (
        <Button
          key={prompt.id}
          secondary
          onClick={() => onPromptClick(prompt.fullText)}
          className="w-full justify-start"
        >
          {prompt.summary}
        </Button>
      ))}
    </div>
  );
}
