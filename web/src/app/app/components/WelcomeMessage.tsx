"use client";

import { useEffect, useState } from "react";
import {
  getTimeOfDayGreeting,
  operatorFirstName,
} from "@/lib/chat/timeOfDayGreeting";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import Logo from "@/refresh-components/Logo";
import Text from "@/refresh-components/texts/Text";
import { MinimalPersonaSnapshot } from "@/app/admin/agents/interfaces";
import { useSettingsContext } from "@/providers/SettingsProvider";
import { useUser } from "@/providers/UserProvider";

export interface WelcomeMessageProps {
  agent?: MinimalPersonaSnapshot;
  isDefaultAgent: boolean;
}

/**
 * Home-page hero greeting. Two states:
 *
 * 1. Default agent (the common case) — renders the redesigned
 *    operator-brain landing hero: a small "AI" pill, a large
 *    time-of-day greeting with the operator's first name italicised
 *    in the brand serif, and a sub-headline. Uses
 *    `useUser()` for the name and a pure time-bucket helper for
 *    the greeting; both behave correctly under SSR/hydration since
 *    we only swap to the live values in a `useEffect`.
 *
 * 2. Custom agent — the original Onyx behaviour: agent avatar +
 *    agent name, so picking a non-default agent still feels
 *    grounded in that agent's identity.
 *
 * The component never throws on missing data (no agent yet, no
 * personalization name): the redesigned default-agent state always
 * renders, and the custom-agent branch returns null while the agent
 * loads (matches prior contract).
 */
export default function WelcomeMessage({
  agent,
  isDefaultAgent,
}: WelcomeMessageProps) {
  const { user } = useUser();
  const settings = useSettingsContext();
  const enterpriseSettings = settings?.enterpriseSettings;

  // Stable defaults for SSR — the live values bind in `useEffect` so the
  // server-rendered HTML and the first client render match.
  const [greeting, setGreeting] = useState("Welcome");
  const [firstName, setFirstName] = useState("there");

  useEffect(() => {
    if (enterpriseSettings?.custom_greeting_message) {
      setGreeting(enterpriseSettings.custom_greeting_message);
    } else {
      setGreeting(getTimeOfDayGreeting());
    }
    setFirstName(operatorFirstName(user));
  }, [enterpriseSettings?.custom_greeting_message, user]);

  if (!isDefaultAgent) {
    if (!agent) return null;
    return (
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

  return (
    <div
      data-testid="chat-intro"
      className="flex flex-col items-center w-full font-['Inter',_sans-serif]"
    >
      <div className="mb-8">
        <Logo folded size={48} />
      </div>

      <h1 className="md:text-4xl lg:text-5xl text-3xl font-medium text-neutral-900 tracking-tight text-center mb-4">
        {greeting},{" "}
        <span className="italic text-[#295EFF] font-serif pr-1">
          {firstName}
        </span>
      </h1>
      <p className="md:text-2xl text-xl font-light text-neutral-500 tracking-tight text-center max-w-2xl mb-2 leading-relaxed">
        What can I help you with?
      </p>
    </div>
  );
}
