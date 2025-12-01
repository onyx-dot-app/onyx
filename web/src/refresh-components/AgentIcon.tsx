import { JSX } from "react";
import crypto from "crypto";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { buildImgUrl } from "@/app/chat/components/files/images/utils";
import { OnyxIcon } from "@/components/icons/icons";
import { cn } from "@/lib/utils";
import { useSettingsContext } from "@/components/settings/SettingsProvider";
import { DEFAULT_ASSISTANT_ID } from "@/lib/constants";
import SvgCheck from "@/icons/check";
import SvgCode from "@/icons/code";
import SvgTwoLineSmall from "@/icons/two-line-small";
import SvgOnyxOctagon from "@/icons/onyx-octagon";
import SvgSearch from "@/icons/search";
import { SvgProps } from "@/icons";

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

interface IconConfig {
  Icon: React.FunctionComponent<SvgProps>;
  className?: string;
}

const iconMap: Record<string, IconConfig> = {
  search: { Icon: SvgSearch, className: "stroke-green-500" },
  check: { Icon: SvgCheck, className: "stroke-green-500" },
  code: { Icon: SvgCode, className: "stroke-orange-500" },
};

export interface AgentIcon2Props {
  id?: number;
  name?: string;
  imageId?: string;
  iconName?: string;

  size?: number;
}

export function AgentIcon2({
  id,
  name,
  imageId,
  iconName,

  size = 18,
}: AgentIcon2Props) {
  const settings = useSettingsContext();

  if (id === DEFAULT_ASSISTANT_ID) {
    return settings.enterpriseSettings?.use_custom_logo ? (
      <img
        alt="Logo"
        src="/api/enterprise-settings/logo"
        loading="lazy"
        className="rounded-full object-cover object-center"
        width={size}
        height={size}
        style={{ objectFit: "contain" }}
      />
    ) : (
      <OnyxIcon size={size} />
    );
  } else if (imageId) {
    return (
      <img
        alt={name}
        src={buildImgUrl(imageId)}
        loading="lazy"
        className={cn(
          "rounded-full object-cover object-center transition-opacity duration-300"
        )}
        width={size}
        height={size}
      />
    );
  } else {
    const iconConfig = iconName && iconMap[iconName];

    if (iconConfig) {
      const { Icon, className } = iconConfig;
      return (
        <div
          className="relative flex flex-col items-center justify-center"
          style={{ width: size, height: size }}
        >
          <SvgOnyxOctagon
            className="absolute inset-0 stroke-text-04"
            style={{ width: size, height: size }}
          />
          <Icon
            className={cn("stroke-text-04", className)}
            style={{ width: size * 0.4, height: size * 0.4 }}
          />
        </div>
      );
    } else {
      // Default icon: two-line-small
      return (
        <div
          className="relative flex flex-col items-center justify-center"
          style={{ width: size, height: size }}
        >
          <SvgOnyxOctagon
            className="absolute inset-0 stroke-text-04"
            style={{ width: size, height: size }}
          />
          <SvgTwoLineSmall className="stroke-text-04 h-8 w-8" />
        </div>
      );
    }
  }
}

export interface AgentIconProps {
  agent: MinimalPersonaSnapshot;
  size?: number;
}

export function AgentIcon({ agent, ...props }: AgentIconProps) {
  return (
    <AgentIcon2
      id={agent.id}
      name={agent.name}
      imageId={agent.uploaded_image_id}
      {...props}
    />
  );
}
