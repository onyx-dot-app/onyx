"use client";

import { OnSubmitProps } from "@/hooks/useChatController";
import { useSelectedAgent } from "@/lib/agents/hooks";
import { Interactive } from "@opal/core";
import { Content } from "@opal/layouts";

export interface SuggestionsProps {
  onSubmit: (props: OnSubmitProps) => void;
}

export default function Suggestions({ onSubmit }: SuggestionsProps) {
  const selectedAgent = useSelectedAgent();

  if (
    !selectedAgent ||
    !selectedAgent.starter_messages ||
    selectedAgent.starter_messages.length === 0
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
    <div className="max-w-(--app-page-main-content-width) flex flex-col w-full p-1">
      {selectedAgent.starter_messages.map(({ message }, index) => (
        <Interactive.Stateless
          key={index}
          variant="default"
          prominence="tertiary"
          onClick={() => handleSuggestionClick(message)}
        >
          <Interactive.Container width="full" rounding="sm" size="lg">
            <Content
              title={message}
              sizePreset="main-ui"
              variant="body"
              width="full"
              color="muted"
            />
          </Interactive.Container>
        </Interactive.Stateless>
      ))}
    </div>
  );
}
