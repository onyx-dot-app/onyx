"use client";

import React from "react";
import Text from "@/refresh-components/Text";
import { SvgProps } from "@/icons";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import {
  ART_ASSISTANT_ID,
  DEFAULT_ASSISTANT_ID,
  GENERAL_ASSISTANT_ID,
  IMAGE_ASSISTANT_ID,
} from "@/lib/constants";
import SvgLightbulbSimple from "@/icons/lightbulb-simple";
import { OnyxIcon } from "@/components/icons/icons";
import { buildImgUrl } from "@/app/chat/components/files/images/utils";
import SvgImage from "@/icons/image";
import { generateIdenticon } from "@/refresh-components/AgentIcon";
import { cn } from "@/lib/utils";

export interface SidebarSectionProps {
  title: string;
  children?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}

export function SidebarSection({
  title,
  children,
  action,
  className,
}: SidebarSectionProps) {
  return (
    <div className={cn("flex flex-col gap-spacing-inline", className)}>
      <div className="px-spacing-interline sticky top-[0rem] bg-background-tint-02 z-10 flex flex-row items-center justify-between">
        <Text secondaryBody text02>
          {title}
        </Text>
        {action && <div className="flex-shrink-0">{action}</div>}
      </div>
      <div className="flex flex-col">{children}</div>
    </div>
  );
}

export function getAgentIcon(
  agent: MinimalPersonaSnapshot
): React.FunctionComponent<SvgProps> {
  if (agent.id === DEFAULT_ASSISTANT_ID) return OnyxIcon;
  if (agent.id === GENERAL_ASSISTANT_ID) return SvgLightbulbSimple;
  if (agent.id === IMAGE_ASSISTANT_ID || agent.id === ART_ASSISTANT_ID)
    return SvgImage;
  if (agent.uploaded_image_id) {
    return ({ className }: SvgProps) => (
      <img
        alt={agent.name}
        src={buildImgUrl(agent.uploaded_image_id as string)}
        loading="lazy"
        className={cn(
          // Ensure dark mode does not tint/alter PNG colors
          "rounded-full object-cover object-center filter-none mix-blend-normal",
          className
        )}
      />
    );
  }
  return () => generateIdenticon((agent.icon_shape || 0).toString(), 16);
}
