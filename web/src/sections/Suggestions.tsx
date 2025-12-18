"use client";

import { OnSubmitProps } from "@/app/chat/hooks/useChatController";
import LineItem from "@/refresh-components/buttons/LineItem";
import { cn } from "@/lib/utils";
import { useAgentsContext } from "@/contexts/AgentsContext";

export interface SuggestionsProps {
  onSubmit: (props: OnSubmitProps) => void;
}

export default function Suggestions({ onSubmit }: SuggestionsProps) {
  const { currentAgent } = useAgentsContext();

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
