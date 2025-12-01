"use client";

import { Logo } from "@/components/logo/Logo";
import { getRandomGreeting } from "@/lib/chat/greetingMessages";
import { cn } from "@/lib/utils";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import Text from "@/refresh-components/texts/Text";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { useMemo } from "react";

interface WelcomeMessageProps {
  liveAssistant?: MinimalPersonaSnapshot;
}

export default function WelcomeMessage({ liveAssistant }: WelcomeMessageProps) {
  // If no agent is active OR the current agent is the default one, we show the Onyx logo.
  const isDefaultAgent = !liveAssistant || liveAssistant.id === 0;
  const greeting = useMemo(getRandomGreeting, []);

  return (
    <div
      data-testid="chat-intro"
      className={cn(
        "row-start-1",
        "self-end",
        "flex",
        "flex-col",
        "items-center",
        "justify-center",
        "mb-6"
      )}
    >
      {isDefaultAgent ? (
        <div
          data-testid="onyx-logo"
          className="flex flex-row items-center gap-4"
        >
          <Logo size="default" />
          <Text headingH2>{greeting}</Text>
        </div>
      ) : (
        <div
          data-testid="assistant-name-display"
          className="flex flex-col items-center gap-3 w-full max-w-[50rem]"
        >
          <div className="flex flex-row items-center gap-3">
            <AgentAvatar agent={liveAssistant} />
            <Text headingH2>{liveAssistant.name}</Text>
          </div>
          {liveAssistant.description && (
            <Text secondaryBody text03>
              {liveAssistant.description}
            </Text>
          )}
        </div>
      )}
    </div>
  );
}
