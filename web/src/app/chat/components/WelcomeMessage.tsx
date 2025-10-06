// import { AssistantIcon } from "@/components/assistants/AssistantIcon";
import { Logo } from "@/components/logo/Logo";
import { cn } from "@/lib/utils";
import { AgentIcon } from "@/refresh-components/AgentIcon";
import Text from "@/refresh-components/Text";
import { useAgentsContext } from "@/refresh-components/contexts/AgentsContext";

export default function WelcomeMessage() {
  const { currentAgent } = useAgentsContext();

  // If no agent is active OR the current agent is the default one, we show the Onyx logo.
  const isDefaultAgent = !currentAgent || currentAgent.id === 0;

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
      <div className="flex items-center">
        {isDefaultAgent ? (
          <div data-testid="onyx-logo">
            <Logo size="large" />
          </div>
        ) : (
          <div className="flex flex-row items-center justify-center gap-padding-button">
            <AgentIcon agent={currentAgent} />
            <Text headingH2>{currentAgent.name}</Text>
          </div>
        )}
      </div>
    </div>
  );
}
