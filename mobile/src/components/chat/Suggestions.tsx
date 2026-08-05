import { Pressable, View } from "react-native";

import { Text } from "@/components/ui/text";
import { AgentStarterMessage } from "@/chat/agents";

interface SuggestionsProps {
  starters: AgentStarterMessage[];
  onSelect: (message: string) => void;
}

// Full-width rows, one per starter (message only); tap = send. Two lines max so narrow-screen
// prompts stay legible.
export function Suggestions({ starters, onSelect }: SuggestionsProps) {
  if (starters.length === 0) return null;

  return (
    <View className="w-full gap-2">
      {starters.map((starter, index) => (
        <Pressable
          key={index}
          onPress={() => onSelect(starter.message)}
          className="w-full rounded-08 border border-border-01 px-12 py-12 active:bg-background-tint-03"
        >
          <Text font="main-ui-body" color="text-03" numberOfLines={2}>
            {starter.message}
          </Text>
        </Pressable>
      ))}
    </View>
  );
}
