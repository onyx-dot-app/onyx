"use client";

import Text from "@/refresh-components/texts/Text";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";

export interface AgentDescriptionProps {
  agent?: MinimalPersonaSnapshot;
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
