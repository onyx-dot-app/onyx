import { AssistantIcon } from "@/components/assistants/AssistantIcon";
import { Logo } from "@/components/logo/Logo";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { getRandomGreeting } from "@/lib/chat/greetingMessages";
import { useMemo } from "react";

interface WelcomeMessageProps {
  assistant: MinimalPersonaSnapshot;
}

export function WelcomeMessage({ assistant }: WelcomeMessageProps) {
  // Memoize the greeting so it doesn't change on re-renders
  const greeting = useMemo(() => getRandomGreeting(), []);

  // For the unified assistant (ID 0), don't show the name
  const isUnifiedAssistant = assistant.id === 0;

  return (
    <div
      data-testid="chat-intro"
      className="row-start-1 self-end flex flex-col items-center text-text-800 justify-center mb-6 transition-opacity duration-300"
    >
      <div className="flex items-center mb-4">
        {isUnifiedAssistant ? (
          <Logo size="large" />
        ) : (
          <>
            <AssistantIcon
              colorOverride="text-text-800"
              assistant={assistant}
              size="large"
            />
            <div className="ml-4 flex justify-center items-center text-center text-3xl font-bold">
              {assistant.name}
            </div>
          </>
        )}
      </div>
      <div className="text-text-600 text-lg text-center max-w-md">
        {greeting}
      </div>
    </div>
  );
}
