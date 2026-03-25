"use client";

import Logo from "@/refresh-components/Logo";
import {
  getRandomGreeting,
  GREETING_MESSAGES,
} from "@/lib/chat/greetingMessages";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import Text from "@/refresh-components/texts/Text";
import { MinimalPersonaSnapshot } from "@/app/admin/agents/interfaces";
import { useState, useEffect } from "react";
import { useSettingsContext } from "@/providers/SettingsProvider";
import FrostedDiv from "@/refresh-components/FrostedDiv";
import { cn } from "@/lib/utils";

export interface WelcomeMessageProps {
  agent?: MinimalPersonaSnapshot;
  isDefaultAgent: boolean;
  /** Optional right-aligned element rendered on the same row as the greeting (e.g. model selector). */
  rightChildren?: React.ReactNode;
  /** When true, the greeting/logo content is hidden (but space is preserved). Used at max models. */
  hideTitle?: boolean;
}

export default function WelcomeMessage({
  agent,
  isDefaultAgent,
  rightChildren,
  hideTitle,
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
      <div data-testid="onyx-logo" className="flex flex-col items-start gap-2">
        <div className="flex items-center justify-center size-9 p-0.5">
          <Logo folded size={32} />
        </div>
        <Text as="p" headingH2>
          {greeting}
        </Text>
      </div>
    );
  } else if (agent) {
    content = (
      <div
        data-testid="agent-name-display"
        className="flex flex-col items-start gap-2"
      >
        <AgentAvatar agent={agent} size={36} />
        <Text as="p" headingH2>
          {agent.name}
        </Text>
      </div>
    );
  }

  // if we aren't using the default agent, we need to wait for the agent info to load
  // before rendering
  if (!content) return null;

  return (
    <FrostedDiv
      data-testid="chat-intro"
      wrapperClassName="w-full"
      className="flex flex-col items-center justify-center gap-3 w-full max-w-[var(--app-page-main-content-width)] mx-auto"
    >
      {rightChildren ? (
        <div className="flex items-end gap-2 w-full">
          <div
            className={cn(
              "flex-1 min-w-0 min-h-[80px] px-2 py-1",
              hideTitle && "invisible"
            )}
          >
            {content}
          </div>
          <div className="shrink-0">{rightChildren}</div>
        </div>
      ) : (
        content
      )}
    </FrostedDiv>
  );
}
