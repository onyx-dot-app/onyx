"use client";

import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { buildImgUrl } from "@/app/chat/components/files/images/utils";
import { OnyxIcon } from "@/components/icons/icons";
import { useSettingsContext } from "@/components/settings/SettingsProvider";
import { DEFAULT_ASSISTANT_ID } from "@/lib/constants";
import CustomAgentAvatar from "@/refresh-components/avatars/CustomAgentAvatar";

export interface AgentIconProps {
  agent: MinimalPersonaSnapshot;
  size?: number;
}

export function AgentAvatar({ agent, ...props }: AgentIconProps) {
  const settings = useSettingsContext();

  if (agent.id === DEFAULT_ASSISTANT_ID) {
    return settings.enterpriseSettings?.use_custom_logo ? (
      <img
        alt="Logo"
        src="/api/enterprise-settings/logo"
        loading="lazy"
        className="rounded-full object-cover object-center"
        width={props.size}
        height={props.size}
        style={{ objectFit: "contain" }}
      />
    ) : (
      <OnyxIcon size={props.size} />
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
      // iconName="..."
      {...props}
    />
  );
}
