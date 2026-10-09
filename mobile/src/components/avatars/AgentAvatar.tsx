import type { ReactNode } from "react";
import { StyleSheet, View } from "react-native";

import { AGENT_AVATAR_ICON_MAP } from "@/components/avatars/agentAvatarIconMap";
import { AgentImage } from "@/components/avatars/AgentImage";
import { Icon } from "@/components/ui/icon";
import { Text } from "@/components/ui/text";
import { DEFAULT_AGENT_ID, MinimalAgent } from "@/chat/agents";
import SvgOnyxLogo from "@/icons/onyx-logo";
import SvgOnyxOctagon from "@/icons/onyx-octagon";
import SvgTwoLineSmall from "@/icons/two-line-small";

export const DEFAULT_AVATAR_SIZE_PX = 18;

interface AgentAvatarProps {
  agent: MinimalAgent;
  size?: number;
}

// id 0 → Onyx logo; uploaded image → circle; icon_name → mapped icon; else monogram or a
// two-line glyph. The enterprise custom-logo for id 0 isn't rendered (no enterprise-settings fetch).
export function AgentAvatar({
  agent,
  size = DEFAULT_AVATAR_SIZE_PX,
}: AgentAvatarProps) {
  if (agent.id === DEFAULT_AGENT_ID) {
    return (
      <Icon as={SvgOnyxLogo} size={size} className="text-theme-primary-05" />
    );
  }

  if (agent.uploaded_image_id) {
    return <AgentImage agentId={agent.id} size={size} />;
  }

  const iconConfig = agent.icon_name
    ? AGENT_AVATAR_ICON_MAP[agent.icon_name]
    : undefined;
  if (iconConfig) {
    return (
      <OctagonWrapper size={size}>
        <Icon
          as={iconConfig.Icon}
          size={size * 0.7}
          className={iconConfig.colorClass}
        />
      </OctagonWrapper>
    );
  }

  const trimmed = agent.name?.trim();
  const firstLetter =
    trimmed && trimmed.length > 0 ? trimmed[0]!.toUpperCase() : undefined;
  if (firstLetter && /^[A-Z]$/.test(firstLetter)) {
    return (
      <OctagonWrapper size={size}>
        <Text color="text-05" style={{ fontSize: size * 0.5 }}>
          {firstLetter}
        </Text>
      </OctagonWrapper>
    );
  }

  return (
    <OctagonWrapper size={size}>
      <Icon as={SvgTwoLineSmall} size={size * 0.8} className="text-text-04" />
    </OctagonWrapper>
  );
}

// Stroke octagon (text-04) with content centered on top.
function OctagonWrapper({
  size,
  children,
}: {
  size: number;
  children: ReactNode;
}) {
  return (
    <View style={{ width: size, height: size }}>
      <View
        style={StyleSheet.absoluteFill}
        className="items-center justify-center"
      >
        <Icon as={SvgOnyxOctagon} size={size} className="text-text-04" />
      </View>
      <View
        style={StyleSheet.absoluteFill}
        className="items-center justify-center"
      >
        {children}
      </View>
    </View>
  );
}
