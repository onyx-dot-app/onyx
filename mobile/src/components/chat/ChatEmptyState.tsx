import { ScrollView } from "react-native";

import { Suggestions } from "@/components/chat/Suggestions";
import { WelcomeMessage } from "@/components/chat/WelcomeMessage";
import { Text } from "@/components/ui/text";
import { MinimalAgent } from "@/chat/agents";

interface ChatEmptyStateProps {
  agent: MinimalAgent | null;
  isDefaultAgent: boolean;
  onStarterSelect: (message: string) => void;
}

// New-chat / empty-session screen: welcome + description + starters. `grow` centers the content
// when short and scrolls when long. The composer is keyboard-pinned to the bottom, so these
// render above it.
export function ChatEmptyState({
  agent,
  isDefaultAgent,
  onStarterSelect,
}: ChatEmptyStateProps) {
  const starters = agent?.starter_messages ?? [];
  const description =
    agent != null && !isDefaultAgent ? agent.description.trim() : "";

  return (
    <ScrollView
      className="flex-1"
      contentContainerClassName="grow items-center justify-center gap-16 px-24 py-24"
      keyboardShouldPersistTaps="handled"
      showsVerticalScrollIndicator={false}
    >
      <WelcomeMessage agent={agent} isDefaultAgent={isDefaultAgent} />
      {description.length > 0 ? (
        <Text
          font="secondary-body"
          color="text-03"
          className="w-full text-center"
        >
          {description}
        </Text>
      ) : null}
      <Suggestions starters={starters} onSelect={onStarterSelect} />
    </ScrollView>
  );
}
