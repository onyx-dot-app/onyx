"use client";

import { OnSubmitProps } from "@/app/app/hooks/useChatController";
import LineItem from "@/refresh-components/buttons/LineItem";
import { useCurrentAgent } from "@/hooks/useAgents";
import { Section } from "@/layouts/general-layouts";

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
      deepResearch: false,
    });
  };

  return (
    <Section padding={0.25} gap={0.25}>
      {currentAgent.starter_messages.map(({ message }, index) => (
        <LineItem key={index} onClick={() => handleSuggestionClick(message)}>
          {message}
        </LineItem>
      ))}
    </Section>
  );
}
