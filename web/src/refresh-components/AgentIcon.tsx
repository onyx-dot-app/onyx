import React from "react";
import crypto from "crypto";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { buildImgUrl } from "@/app/chat/components/files/images/utils";
import {
  ArtAsistantIcon,
  GeneralAssistantIcon,
  OnyxIcon,
} from "@/components/icons/icons";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/Text";

const SIZE = 24;

function md5ToBits(str: string): number[] {
  const md5hex = crypto.createHash("md5").update(str).digest("hex");
  const bits: number[] = [];
  for (let i = 0; i < md5hex.length; i += 2) {
    const hex = md5hex.substr(i, 2);
    const num = parseInt(hex, 16);
    for (let j = 7; j >= 0; j--) {
      bits.push((num >> j) & 1);
    }
  }
  return bits;
}

export function generateIdenticon(str: string): JSX.Element {
  const bits = md5ToBits(str);
  const squares = [];

  for (let i = 0; i < 64; i++) {
    const bit = bits[i % bits.length];
    if (bit) {
      const x = (i % 8) * SIZE;
      const y = Math.floor(i / 8) * SIZE;
      squares.push(
        <rect
          key={i}
          x={x}
          y={y}
          width={SIZE}
          height={SIZE}
          fill="currentColor"
        />
      );
    }
  }

  return (
    <svg
      width={SIZE}
      height={SIZE}
      viewBox={`0 0 ${SIZE} ${SIZE}`}
      className="rounded-full"
    >
      {squares}
    </svg>
  );
}

export interface AgentIconProps {
  agent: MinimalPersonaSnapshot;
}

export function AgentIcon({ agent }: AgentIconProps) {
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <div className="text-text-04">
            {agent.id == -3 ? (
              <ArtAsistantIcon size={SIZE} />
            ) : agent.id == 0 ? (
              <OnyxIcon size={SIZE} />
            ) : agent.id == -1 ? (
              <GeneralAssistantIcon size={SIZE} />
            ) : agent.uploaded_image_id ? (
              <img
                alt={agent.name}
                src={buildImgUrl(agent.uploaded_image_id)}
                loading="lazy"
                className={cn(
                  "rounded-full object-cover object-center transition-opacity duration-300"
                )}
              />
            ) : (
              generateIdenticon((agent.icon_shape || 0).toString())
            )}
          </div>
        </TooltipTrigger>
        <TooltipContent>
          <Text inverted>{agent.description}</Text>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
