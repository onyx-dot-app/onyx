"use client";

import { Text } from "@opal/components";
import { MinimalAgent } from "@/lib/agents/types";

export interface AgentDescriptionProps {
  agent?: MinimalAgent;
}

export default function AgentDescription({ agent }: AgentDescriptionProps) {
  if (!agent?.description) return null;

  return (
    <div className="w-full min-w-0">
      <Text
        as="p"
        font="secondary-body"
        color="text-03"
        textPosition="text-center"
        wordWrap="wrap-break-word"
      >
        {agent.description}
      </Text>
    </div>
  );
}
