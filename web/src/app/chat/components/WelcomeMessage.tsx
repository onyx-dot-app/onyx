import { AssistantIcon } from "@/components/assistants/AssistantIcon";
import { Logo } from "@/components/logo/Logo";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/Text";

interface WelcomeMessageProps {
  assistant: MinimalPersonaSnapshot;
}

export function WelcomeMessage({ assistant }: WelcomeMessageProps) {
  // For the unified assistant (ID 0), show greeting message
  const isUnifiedAssistant = assistant.id === 0;

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
        {isUnifiedAssistant ? (
          <div data-testid="onyx-logo">
            <Logo size="large" />
          </div>
        ) : (
          <div className="flex flex-row items-center justify-center gap-padding-button">
            <AssistantIcon assistant={assistant} size="large" />
            <Text headingH2>{assistant.name}</Text>
          </div>
        )}
      </div>
    </div>
  );
}
