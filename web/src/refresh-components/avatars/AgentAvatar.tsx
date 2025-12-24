"use client";

import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { buildImgUrl } from "@/app/chat/components/files/images/utils";
import { OnyxIcon } from "@/components/icons/icons";
import { useSettingsContext } from "@/components/settings/SettingsProvider";
import {
  DEFAULT_AGENT_AVATAR_SIZE_PX,
  DEFAULT_ASSISTANT_ID,
} from "@/lib/constants";
import CustomAgentAvatar from "@/refresh-components/avatars/CustomAgentAvatar";
import Image from "next/image";

export interface AgentAvatarProps {
  agent: MinimalPersonaSnapshot;
  size?: number;
}

export default function AgentAvatar({
  agent,
  size = DEFAULT_AGENT_AVATAR_SIZE_PX,
  ...props
}: AgentAvatarProps) {
  const settings = useSettingsContext();

  if (agent.id === DEFAULT_ASSISTANT_ID) {
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
      <OnyxIcon size={size} className="shrink-0" />
    );
  }

  return (
    <CustomAgentAvatar
      name={agent.name}
      src={
        agent.uploaded_image_id
          ? buildImgUrl(agent.uploaded_image_id)
          : undefined
      }
      iconName={agent.icon_name}
      size={size}
      {...props}
    />
  );
}
