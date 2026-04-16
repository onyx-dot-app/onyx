"use client";

import { OnSubmitProps } from "@/hooks/useChatController";
import { MinimalPersonaSnapshot } from "@/app/admin/agents/interfaces";
import { Interactive } from "@opal/core";
import { Content } from "@opal/layouts";

interface TutorSuggestionsProps {
  agent: MinimalPersonaSnapshot;
  onSubmit: (props: OnSubmitProps) => void;
}

export default function TutorSuggestions({
  agent,
  onSubmit,
}: TutorSuggestionsProps) {
  if (!agent.starter_messages || agent.starter_messages.length === 0) {
    return null;
  }

  function handleSuggestionClick(message: string) {
    onSubmit({
      message,
      currentMessageFiles: [],
      deepResearch: false,
    });
  }

  return (
    <div className="flex flex-col w-full p-1">
      {agent.starter_messages.map(({ message }, index) => (
        <Interactive.Stateless
          key={index}
          variant="default"
          prominence="tertiary"
          onClick={() => handleSuggestionClick(message)}
        >
          <Interactive.Container
            widthVariant="full"
            roundingVariant="sm"
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
        </Interactive.Stateless>
      ))}
    </div>
  );
}
