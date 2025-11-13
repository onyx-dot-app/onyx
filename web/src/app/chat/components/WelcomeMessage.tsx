// import { AssistantIcon } from "@/components/assistants/AssistantIcon";
import { Logo } from "@/components/logo/Logo";
import { getRandomGreeting } from "@/lib/chat/greetingMessages";
import { cn } from "@/lib/utils";
import AgentIcon from "@/refresh-components/AgentIcon";
import Text from "@/refresh-components/texts/Text";
import { useAgentsContext } from "@/refresh-components/contexts/AgentsContext";
import { useMemo } from "react";

export default function WelcomeMessage() {
  const { currentAgent } = useAgentsContext();

  // If no agent is active OR the current agent is the default one, we show the Onyx logo.
  const isDefaultAgent = !currentAgent || currentAgent.id === 0;
  const greeting = useMemo(getRandomGreeting, []);

  return (
    <div
      data-testid="chat-intro"
      className={cn(
        "row-start-1",
        "self-end",
        "flex",
        "flex-col",
        "items-center",
        "justify-center",
        "mb-6"
      )}
    >
      {isDefaultAgent ? (
        <div
          data-testid="onyx-logo"
          className="flex flex-row items-center gap-4"
        >
          <Logo size="default" />
          <Text headingH2>{greeting}</Text>
        </div>
      ) : (
        <div
          data-testid="assistant-name-display"
          className="flex flex-col items-center gap-3 w-full max-w-[50rem]"
        >
          <div className="flex flex-row items-center gap-3">
            <AgentIcon agent={currentAgent} />
            <Text headingH2>{currentAgent.name}</Text>
          </div>
          {currentAgent.description && (
            <Text secondaryBody text03>
              {currentAgent.description}
            </Text>
          )}
        </div>
      )}
    </div>
  );
}
