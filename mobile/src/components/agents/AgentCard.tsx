import { View } from "react-native";

import { AgentAvatar } from "@/components/avatars/AgentAvatar";
import { Card } from "@/components/ui/card";
import { Text } from "@/components/ui/text";
import { MinimalAgent } from "@/chat/agents";

interface AgentCardProps {
  agent: MinimalAgent;
  onPress: (agent: MinimalAgent) => void;
}

// Gallery card: tapping anywhere starts a chat. Owner/action counts, pin/edit/share, and the
// featured badge are intentionally omitted (select-only).
export function AgentCard({ agent, onPress }: AgentCardProps) {
  return (
    <Card onPress={() => onPress(agent)} className="flex-row items-start gap-8">
      <View className="pt-0.5">
        <AgentAvatar agent={agent} size={24} />
      </View>
      <View className="flex-1">
        <Text font="main-content-emphasis" color="text-05" numberOfLines={1}>
          {agent.name}
        </Text>
        {agent.description.trim() ? (
          <Text
            font="secondary-body"
            color="text-03"
            numberOfLines={2}
            className="pt-2"
          >
            {agent.description}
          </Text>
        ) : null}
      </View>
    </Card>
  );
}
