"use client";

import { OnSubmitProps } from "@/app/chat/hooks/useChatController";
import LineItem from "@/refresh-components/buttons/LineItem";
import { useCurrentAgent } from "@/lib/hooks/useCurrentAgent";
import { cn } from "@/lib/utils";

interface SuggestionsProps {
  onSubmit: (props: OnSubmitProps) => void;
}

export function Suggestions({ onSubmit }: SuggestionsProps) {
  const { currentAgent } = useCurrentAgent();

  if (
    !currentAgent ||
    !currentAgent.starter_messages ||
    currentAgent.starter_messages.length === 0
  )
    return null;

  const handleSuggestionClick = (suggestion: string) => {
    onSubmit({
      message: suggestion,
    });
  };

  return (
    <div className={cn("flex flex-col w-full p-1 gap-1")}>
      {currentAgent.starter_messages.map(({ message }, index) => (
        <LineItem key={index} onClick={() => handleSuggestionClick(message)}>
          {message}
        </LineItem>
      ))}
    </div>
  );
}
