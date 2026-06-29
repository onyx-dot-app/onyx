import { useState } from "react";
import { View } from "react-native";

import { Icon } from "@/components/ui/icon";
import { Text } from "@/components/ui/text";
import SvgOnyxLogo from "@/icons/onyx-logo";
import { getRandomGreeting } from "@/lib/greetings";

// Mirrors web's `WelcomeMessage` (default-agent variant): Onyx logo + random
// greeting. The agent variant (avatar + name) lands in PR 5.
export function WelcomeMessage() {
  const [greeting] = useState(getRandomGreeting);

  return (
    <View className="items-center gap-8">
      <Icon as={SvgOnyxLogo} size={32} className="text-text-05" />
      <Text font="heading-h2" color="text-05">
        {greeting}
      </Text>
    </View>
  );
}
