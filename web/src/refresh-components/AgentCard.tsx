"use client";

import React from "react";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import AgentIcon from "@/refresh-components/AgentIcon";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import SvgBubbleText from "@/icons/bubble-text";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
} from "@/components/ui/card";
import { useAppRouter } from "@/hooks/appNavigation";

interface AgentCardProps {
  agent: MinimalPersonaSnapshot;
}

export default function AgentCard({ agent }: AgentCardProps) {
  const route = useAppRouter();

  return (
    <Card className="flex flex-col h-full">
      {/* Header with icon and name */}
      <CardHeader className="flex flex-row items-center gap-3 pb-2 dbg-red">
        <AgentIcon agent={agent} size={24} />
        <Text mainContentEmphasis className="flex-1">
          {agent.name}
        </Text>
      </CardHeader>

      {/* Description section - bg-background-tint-00 */}
      <CardContent className="flex-1 bg-background-tint-00 px-6 py-4">
        <Text text03>{agent.description}</Text>
      </CardContent>

      {/* Footer section - bg-background-tint-01 */}
      <CardFooter className="bg-background-tint-01 px-6 py-4 flex flex-row items-center justify-between">
        {/* Left side - creator and actions */}
        <div className="flex flex-col gap-1">
          <Text secondaryBody text02>
            By {agent.owner?.email || "Onyx"}
          </Text>
          <Text secondaryBody text02>
            {agent.tools.length > 0
              ? `${agent.tools.length} Action${
                  agent.tools.length > 1 ? "s" : ""
                }`
              : "No Actions"}
          </Text>
        </div>

        {/* Right side - Start Chat button */}
        <Button
          secondary
          leftIcon={SvgBubbleText}
          onClick={() => route({ agentId: agent.id })}
        >
          Start Chat
        </Button>
      </CardFooter>
    </Card>
  );
}
