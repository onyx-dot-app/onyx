import React from "react";
import crypto from "crypto";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { buildImgUrl } from "@/app/chat/components/files/images/utils";
import { ArtAsistantIcon, OnyxIcon } from "@/components/icons/icons";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import { useSettingsContext } from "@/components/settings/SettingsProvider";

function md5ToBits(str: string): number[] {
  const md5hex = crypto.createHash("md5").update(str).digest("hex");
  const bits: number[] = [];
  for (let i = 0; i < md5hex.length; i += 2) {
    const byteVal = parseInt(md5hex.substring(i, i + 2), 16);
    for (let b = 7; b >= 0; b--) {
      bits.push((byteVal >> b) & 1);
    }
  }
  return bits;
}

export function generateIdenticon(str: string, size: number) {
  const bits = md5ToBits(str);
  const gridSize = 5;
  const halfCols = 4;
  const cellSize = size / gridSize;

  let bitIndex = 0;
  const squares: JSX.Element[] = [];

  for (let row = 0; row < gridSize; row++) {
    for (let col = 0; col < halfCols; col++) {
      const bit = bits[bitIndex % bits.length];
      bitIndex++;

      if (bit === 1) {
        const xPos = col * cellSize;
        const yPos = row * cellSize;
        squares.push(
          <rect
            key={`${xPos}-${yPos}`}
            x={xPos - 0.5}
            y={yPos - 0.5}
            width={cellSize + 1}
            height={cellSize + 1}
            fill="var(--background-neutral-inverted-02)"
            stroke="var(--background-neutral-inverted-02)"
          />
        );

        const mirrorCol = gridSize - 1 - col;
        if (mirrorCol !== col) {
          const mirrorX = mirrorCol * cellSize;
          squares.push(
            <rect
              key={`a-${mirrorX}-${yPos}`}
              x={mirrorX - 0.5}
              y={yPos - 0.5}
              width={cellSize + 1}
              height={cellSize + 1}
              fill="var(--background-neutral-inverted-02)"
              stroke="var(--background-neutral-inverted-02)"
            />
          );
        }
      }
    }
  }

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      style={{ display: "block" }}
    >
      {squares}
    </svg>
  );
}

export interface AgentIconProps {
  agent: MinimalPersonaSnapshot;
  size?: number;
}

export function AgentIcon({ agent, size = 24 }: AgentIconProps) {
  const settings = useSettingsContext();

  // Check if whitelabeling is enabled for the default assistant
  const shouldUseWhitelabelLogo =
    agent.id === 0 && settings?.enterpriseSettings?.use_custom_logo === true;

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <div className="text-text-04">
            {agent.id === -3 ? (
              <ArtAsistantIcon size={size} />
            ) : agent.id === 0 ? (
              shouldUseWhitelabelLogo ? (
                <img
                  alt="Logo"
                  src="/api/enterprise-settings/logo"
                  loading="lazy"
                  className={cn(
                    "rounded-full object-cover object-center transition-opacity duration-300"
                  )}
                  width={size}
                  height={size}
                  style={{ objectFit: "contain" }}
                />
              ) : (
                <OnyxIcon size={size} />
              )
            ) : agent.uploaded_image_id ? (
              <img
                alt={agent.name}
                src={buildImgUrl(agent.uploaded_image_id)}
                loading="lazy"
                className={cn(
                  "rounded-full object-cover object-center transition-opacity duration-300"
                )}
                width={size}
                height={size}
              />
            ) : (
              generateIdenticon((agent.icon_shape || 0).toString(), size)
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
