"use client";

import Logo from "@/refresh-components/Logo";
import {
  getRandomGreeting,
  GREETING_MESSAGES,
} from "@/lib/chat/greetingMessages";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import Text from "@/refresh-components/texts/Text";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { useState, useEffect } from "react";
import { useSettingsContext } from "@/components/settings/SettingsProvider";
import { Section } from "@/layouts/general-layouts";

export interface WelcomeMessageProps {
  agent?: MinimalPersonaSnapshot;
  isDefaultAgent: boolean;
}

export default function WelcomeMessage({
  agent,
  isDefaultAgent,
}: WelcomeMessageProps) {
  const settings = useSettingsContext();
  const enterpriseSettings = settings?.enterpriseSettings;

  // Use a stable default for SSR, then randomize on client after hydration
  const [greeting, setGreeting] = useState(GREETING_MESSAGES[0]);

  useEffect(() => {
    if (enterpriseSettings?.custom_greeting_message) {
      setGreeting(enterpriseSettings.custom_greeting_message);
    } else {
      setGreeting(getRandomGreeting());
    }
  }, [enterpriseSettings?.custom_greeting_message]);

  let content: React.ReactNode = null;

  if (isDefaultAgent) {
    content = (
      <div data-testid="onyx-logo">
        <Section flexDirection="row" gap={1}>
          <Logo folded size={32} />
          <Text as="p" headingH2>
            {greeting}
          </Text>
        </Section>
      </div>
    );
  } else if (agent) {
    content = (
      <Section gap={0.25}>
        <div data-testid="assistant-name-display">
          <Section flexDirection="row" gap={1}>
            <AgentAvatar agent={agent} size={36} />
            <Text as="p" headingH2>
              {agent.name}
            </Text>
          </Section>
        </div>
        {agent.description && (
          <Text secondaryBody text03>
            {agent.description}
          </Text>
        )}
      </Section>
    );
  }

  // if we aren't using the default agent, we need to wait for the agent info to load
  // before rendering
  if (!content) return null;

  return (
    <div data-testid="chat-intro" className="w-[min(50rem,100%)]">
      {content}
    </div>
  );
}
