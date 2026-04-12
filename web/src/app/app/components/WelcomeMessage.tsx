"use client";

import Logo from "@/refresh-components/Logo";
import {
  getRandomGreeting,
  getGreetingMessages,
} from "@/lib/chat/greetingMessages";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import Text from "@/refresh-components/texts/Text";
import { MinimalPersonaSnapshot } from "@/app/admin/agents/interfaces";
import { useState, useEffect } from "react";
import { useSettingsContext } from "@/providers/SettingsProvider";
import FrostedDiv from "@/refresh-components/FrostedDiv";
import { Section } from "@/layouts/general-layouts";
import { useTranslations } from "next-intl";

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
  const t = useTranslations("chat");

  // Use a stable default for SSR, then randomize on client after hydration
  const [greeting, setGreeting] = useState(getGreetingMessages(t)[0]);

  useEffect(() => {
    if (enterpriseSettings?.custom_greeting_message) {
      setGreeting(enterpriseSettings.custom_greeting_message);
    } else {
      setGreeting(getRandomGreeting(t));
    }
  }, [enterpriseSettings?.custom_greeting_message, t]);

  let content: React.ReactNode = null;

  if (isDefaultAgent) {
    content = (
      <Section
        data-testid="onyx-logo"
        flexDirection="column"
        alignItems="start"
        gap={0.5}
        width="fit"
      >
        <Logo folded size={32} />
        <Text as="p" headingH2>
          {greeting}
        </Text>
      </Section>
    );
  } else if (agent) {
    content = (
      <Section
        data-testid="agent-name-display"
        flexDirection="column"
        alignItems="start"
        gap={0.5}
        width="fit"
      >
        <AgentAvatar agent={agent} size={36} />
        <Text as="p" headingH2>
          {agent.name}
        </Text>
      </Section>
    );
  }

  // if we aren't using the default agent, we need to wait for the agent info to load
  // before rendering
  if (!content) return null;

  return (
    <FrostedDiv
      data-testid="chat-intro"
      className="flex flex-col items-center justify-center gap-3 w-full max-w-[var(--app-page-main-content-width)]"
    >
      {content}
    </FrostedDiv>
  );
}
