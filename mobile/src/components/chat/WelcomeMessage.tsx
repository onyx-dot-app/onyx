import { useState } from "react";
import { View } from "react-native";

import { AgentAvatar } from "@/components/avatars/AgentAvatar";
import { Icon } from "@/components/ui/icon";
import { Text } from "@/components/ui/text";
import { MinimalAgent } from "@/chat/agents";
import SvgOnyxLogo from "@/icons/onyx-logo";
import { getRandomGreeting } from "@/lib/greetings";

interface WelcomeMessageProps {
  agent: MinimalAgent | null;
  isDefaultAgent: boolean;
}

export function WelcomeMessage({ agent, isDefaultAgent }: WelcomeMessageProps) {
  const [greeting] = useState(getRandomGreeting);

  if (agent && !isDefaultAgent) {
    return (
      <View className="items-center gap-8">
        <AgentAvatar agent={agent} size={36} />
        <Text
          font="heading-h2"
          color="text-05"
          numberOfLines={2}
          className="text-center"
        >
          {agent.name}
        </Text>
      </View>
    );
  }

  return (
    <View className="items-center gap-8">
      <Icon as={SvgOnyxLogo} size={32} className="text-text-05" />
      <Text font="heading-h2" color="text-05">
        {greeting}
      </Text>
    </View>
  );
}
