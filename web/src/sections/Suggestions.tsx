"use client";

import { OnSubmitProps } from "@/app/chat/hooks/useChatController";
import LineItem from "@/refresh-components/buttons/LineItem";
import { useCurrentAgent } from "@/hooks/useAgents";
import { cn } from "@/lib/utils";

export interface SuggestionsProps {
  onSubmit: (props: OnSubmitProps) => void;
}

export default function Suggestions({ onSubmit }: SuggestionsProps) {
  const currentAgent = useCurrentAgent();

  if (
    !currentAgent ||
    !currentAgent.starter_messages ||
    currentAgent.starter_messages.length === 0
  )
    return null;

  const handleSuggestionClick = (suggestion: string) => {
    onSubmit({
      message: suggestion,
      currentMessageFiles: [],
      useAgentSearch: false,
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
