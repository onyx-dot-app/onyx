// AgentAvatar.tsx — small agent avatar for the timeline header. Functional
// stand-in for web AgentAvatar: a tinted circle with the agent's initial (or a
// sparkle glyph when no name). Per-agent uploaded images/icons are deferred.

import { View } from "react-native";

import type { MinimalAgent } from "@/lib/types";
import { Text } from "@/components/opal";
import { useThemeColors } from "@/theme/ThemeProvider";
import { SvgSparkle } from "@/components/icons";

interface AgentAvatarProps {
  agent?: MinimalAgent | null;
  size?: number;
}

export function AgentAvatar({ agent, size = 24 }: AgentAvatarProps) {
  const colors = useThemeColors();
  const initial = agent?.name?.trim()?.[0]?.toUpperCase();

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
      {initial ? (
        <Text font="figure-small-value" color="text-04">
          {initial}
        </Text>
      ) : (
        <SvgSparkle size={size * 0.55} color="text-04" />
      )}
    </View>
  );
}

export default AgentAvatar;
