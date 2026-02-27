"use client";

import { OnSubmitProps } from "@/hooks/useChatController";
import { useCurrentAgent } from "@/hooks/useAgents";
import { Interactive } from "@opal/core";
import { Content } from "@opal/layouts";

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
    <div className="max-w-[var(--app-page-main-content-width)] flex flex-col w-full p-1">
      {currentAgent.starter_messages.map(({ message }, index) => (
        <Interactive.Base
          key={index}
          variant="default"
          prominence="tertiary"
          onClick={() => handleSuggestionClick(message)}
        >
          <Interactive.Container
            widthVariant="full"
            roundingVariant="compact"
            heightVariant="lg"
          >
            <Content
              title={message}
              sizePreset="main-ui"
              variant="body"
              widthVariant="full"
              prominence="muted"
            />
          </Interactive.Container>
        </Interactive.Base>
      ))}
    </div>
  );
}
