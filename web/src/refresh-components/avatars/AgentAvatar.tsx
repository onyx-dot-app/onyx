"use client";

import { MinimalAgent } from "@/lib/agents/types";
import { buildAgentAvatarUrl } from "@/lib/agents/utils";
import { useSettingsContext } from "@/providers/SettingsProvider";
import { DEFAULT_AVATAR_SIZE_PX, DEFAULT_AGENT_ID } from "@/lib/constants";
import CustomAgentAvatar from "@/refresh-components/avatars/CustomAgentAvatar";
import Image from "next/image";
import { APP_NAME } from "@/lib/brand";

export interface AgentAvatarProps {
  agent: MinimalAgent;
  size?: number;
}

export default function AgentAvatar({
  agent,
  size = DEFAULT_AVATAR_SIZE_PX,
  ...props
}: AgentAvatarProps) {
  const settings = useSettingsContext();

  if (agent.id === DEFAULT_AGENT_ID) {
    return settings.enterpriseSettings?.use_custom_logo ? (
      <div
        className="aspect-square rounded-full overflow-hidden relative"
        style={{ height: size, width: size }}
      >
        <Image
          alt="Logo"
          src="/api/enterprise-settings/logo"
          fill
          className="object-cover object-center"
          sizes={`${size}px`}
        />
      </div>
    ) : (
      <div
        className="shrink-0 rounded-full bg-theme-primary-05 text-text-inverted-05 flex items-center justify-center font-bold"
        style={{ height: size, width: size, fontSize: Math.max(12, size * 0.5) }}
        aria-label={APP_NAME}
      >
        G
      </div>
    );
  }

  return (
    <CustomAgentAvatar
      name={agent.name}
      src={agent.uploaded_image_id ? buildAgentAvatarUrl(agent.id) : undefined}
      iconName={agent.icon_name}
      size={size}
      {...props}
    />
  );
}
