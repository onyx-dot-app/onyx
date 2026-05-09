"use client";

import Text from "@/refresh-components/texts/Text";
import { MinimalAgentSnapshot } from "@/lib/agents/types";

export interface AgentDescriptionProps {
  agent?: MinimalAgentSnapshot;
}

export default function AgentDescription({ agent }: AgentDescriptionProps) {
  if (!agent?.description) return null;

  return (
    <Text
      as="p"
      secondaryBody
      text03
      className="w-full min-w-0 text-center break-words"
    >
      {agent.description}
    </Text>
  );
}
