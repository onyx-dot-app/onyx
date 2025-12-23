"use client";

import Logo from "@/refresh-components/Logo";
import { getRandomGreeting } from "@/lib/chat/greetingMessages";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import Text from "@/refresh-components/texts/Text";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { useContext, useMemo } from "react";
import { SettingsContext } from "@/components/settings/SettingsProvider";

export interface WelcomeMessageProps {
  agent?: MinimalPersonaSnapshot;
  isDefaultAgent: boolean;
}

export default function WelcomeMessage({
  agent,
  isDefaultAgent,
}: WelcomeMessageProps) {
  let content: React.ReactNode = null;
  const settings = useContext(SettingsContext);
  const enterpriseSettings = settings?.enterpriseSettings;
  const greeting = useMemo(() => {
    if (enterpriseSettings?.custom_greeting_message) {
      return enterpriseSettings?.custom_greeting_message;
    }
    return getRandomGreeting();
  }, [enterpriseSettings]);

  if (isDefaultAgent) {
    content = (
      <div data-testid="onyx-logo" className="flex flex-row items-center gap-4">
        <Logo folded size={32} />
        <Text headingH2>{greeting}</Text>
      </div>
    );
  } else if (agent) {
    content = (
      <div className="flex flex-col items-center gap-3 w-full max-w-[50rem]">
        <div
          data-testid="assistant-name-display"
          className="flex flex-row items-center gap-3"
        >
          <AgentAvatar agent={agent} size={36} />
          <Text headingH2>{agent.name}</Text>
        </div>
        {agent.description && (
          <Text secondaryBody text03>
            {agent.description}
          </Text>
        )}
      </div>
    );
  }

  // if we aren't using the default agent, we need to wait for the agent info to load
  // before rendering
  if (!content) return null;

  return (
    <div
      data-testid="chat-intro"
      className="flex flex-col items-center justify-center"
    >
      {content}
    </div>
  );
}
