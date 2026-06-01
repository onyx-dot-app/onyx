// Native mirror of web AgentAvatar. Per-agent uploaded images/icons are deferred.

import { View } from "react-native";

import type { MinimalAgent } from "@/lib/types";
import { Text } from "@/components/opal";
import { useThemeColors } from "@/theme/ThemeProvider";
import { OnyxLogo } from "@/components/ui/logos";

interface AgentAvatarProps {
  agent?: MinimalAgent | null;
  size?: number;
}

export function AgentAvatar({ agent, size = 24 }: AgentAvatarProps) {
  const colors = useThemeColors();
  const initial = agent?.name?.trim()?.[0]?.toUpperCase();

  // No name -> Onyx brand mark (transparent SVG, no circle/background).
  if (!initial) {
    return (
      <View style={{ width: size, height: size, alignItems: "center", justifyContent: "center" }}>
        <OnyxLogo size={size} color={colors["theme-primary-05"]} />
      </View>
    );
  }

  return (
    <View
      style={{
        width: size,
        height: size,
        borderRadius: size / 2,
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: colors["background-tint-02"],
      }}
    >
      <Text font="figure-small-value" color="text-04">
        {initial}
      </Text>
    </View>
  );
}

export default AgentAvatar;
