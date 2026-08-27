"use client";

import { Logo } from "@/lib/app/components";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import Text from "@/refresh-components/texts/Text";
import { MinimalAgent } from "@/lib/agents/types";
import { useState, useEffect } from "react";
import { useSettings } from "@/lib/settings/hooks";
import FrostedDiv from "@/refresh-components/FrostedDiv";
import { Section } from "@/layouts/general-layouts";
import { SvgEyeClosed } from "@opal/icons";
import { useIncognito } from "@/providers/IncognitoProvider";
import { useTranslations } from "next-intl";

export interface WelcomeMessageProps {
  agent?: MinimalAgent;
  isDefaultAgent: boolean;
}

export default function WelcomeMessage({
  agent,
  isDefaultAgent,
}: WelcomeMessageProps) {
  const t = useTranslations("chat.welcome");
  const settings = useSettings();

  // Use a stable default for SSR, then randomize on client after hydration
  const [greeting, setGreeting] = useState(t("greeting.helpText"));

  useEffect(() => {
    if (settings.enterprise?.custom_greeting_message) {
      setGreeting(settings.enterprise.custom_greeting_message);
    } else {
      setGreeting(
        Math.random() < 0.5 ? t("greeting.helpText") : t("greeting.startText")
      );
    }
  }, [settings.enterprise?.custom_greeting_message, t]);

  const { incognitoEnabled } = useIncognito();

  let content: React.ReactNode = null;

  if (incognitoEnabled) {
    content = (
      <Section
        data-testid="incognito-intro"
        flexDirection="column"
        alignItems="start"
        gap={0.5}
        width="fit"
      >
        <SvgEyeClosed size={32} className="text-text-04" />
        <Text as="p" headingH2>
          {t("incognito.title")}
        </Text>
      </Section>
    );
  } else if (isDefaultAgent) {
    content = (
      <Section
        data-testid="onyx-logo"
        flexDirection="column"
        alignItems="start"
        gap={2}
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
        gap={2}
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
      className="flex flex-col items-center justify-center gap-3 w-full max-w-(--app-page-main-content-width)"
    >
      {content}
    </FrostedDiv>
  );
}
