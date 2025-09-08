import { AssistantIcon } from "@/components/assistants/AssistantIcon";
import { Logo } from "@/components/logo/Logo";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { getRandomGreeting } from "@/lib/chat/greetingMessages";
import { useMemo } from "react";
import { cn } from "@/lib/utils";

interface WelcomeMessageProps {
  assistant: MinimalPersonaSnapshot;
}

export function WelcomeMessage({ assistant }: WelcomeMessageProps) {
  // Memoize the greeting so it doesn't change on re-renders (only for unified assistant)
  const greeting = useMemo(() => getRandomGreeting(), []);

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
        "text-text-800",
        "justify-center",
        "mb-6",
        "transition-opacity",
        "duration-300"
      )}
    >
      <div className="flex items-center">
        {isUnifiedAssistant ? (
          <>
            <div data-testid="onyx-logo">
              <Logo size="large" />
            </div>
            <div
              data-testid="greeting-message"
              className="ml-6 text-text-600 dark:text-neutral-100 text-3xl font-bold max-w-md"
            >
              {greeting}
            </div>
          </>
        ) : (
          <>
            <AssistantIcon
              colorOverride="text-text-800"
              assistant={assistant}
              size="large"
            />
            <div
              data-testid="assistant-name-display"
              className="ml-4 flex justify-center items-center text-center text-3xl font-bold"
            >
              {assistant.name}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
