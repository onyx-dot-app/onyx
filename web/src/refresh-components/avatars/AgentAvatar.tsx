"use client";

import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { buildImgUrl } from "@/app/chat/components/files/images/utils";
import { OnyxIcon } from "@/components/icons/icons";
import { useSettingsContext } from "@/components/settings/SettingsProvider";
import { DEFAULT_ASSISTANT_ID } from "@/lib/constants";
import CustomAgentAvatar from "@/refresh-components/avatars/CustomAgentAvatar";

export interface AgentAvatarProps {
  agent: MinimalPersonaSnapshot;
  size?: number;
}

export default function AgentAvatar({ agent, ...props }: AgentAvatarProps) {
  const settings = useSettingsContext();

  if (agent.id === DEFAULT_ASSISTANT_ID) {
    return settings.enterpriseSettings?.use_custom_logo ? (
      <div
        className="aspect-square rounded-full overflow-hidden"
        style={{ height: props.size, width: props.size }}
      >
        <img
          alt="Logo"
          src="/api/enterprise-settings/logo"
          loading="lazy"
          className="h-full w-full object-contain object-center"
        />
      </div>
    ) : (
      <OnyxIcon size={props.size} className="" />
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
      {...props}
    />
  );
}
