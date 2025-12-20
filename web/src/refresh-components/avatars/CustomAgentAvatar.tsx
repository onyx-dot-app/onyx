"use client";

import { cn } from "@/lib/utils";
import type { IconProps } from "@opal/types";
import Text from "@/refresh-components/texts/Text";
import Image from "next/image";
import { DEFAULT_AGENT_AVATAR_SIZE_PX } from "@/lib/constants";
import {
  SvgCheck,
  SvgCode,
  SvgOnyxOctagon,
  SvgSearch,
  SvgTwoLineSmall,
} from "@opal/icons";

interface IconConfig {
  Icon: React.FunctionComponent<IconProps>;
  className?: string;
}

export const iconMap: Record<string, IconConfig> = {
  search: { Icon: SvgSearch, className: "stroke-green-500" },
  check: { Icon: SvgCheck, className: "stroke-green-500" },
  code: { Icon: SvgCode, className: "stroke-orange-500" },
};

export function asdf(a: keyof typeof iconMap, size?: number): React.ReactNode {
  const iconConfig = iconMap[a];
  if (!iconConfig) return null;

  const { Icon } = iconConfig;

  return (
    <SvgOctagonWrapper size={(size = DEFAULT_AGENT_AVATAR_SIZE_PX)}>
      <Icon />
    </SvgOctagonWrapper>
  );
}

interface SvgOctagonWrapperProps {
  size: number;
  children: React.ReactNode;
}

function SvgOctagonWrapper({ size, children }: SvgOctagonWrapperProps) {
  return (
    <div className="relative flex flex-col items-center justify-center">
      <div className="absolute inset-0 flex items-center justify-center">
        {children}
      </div>
      <SvgOnyxOctagon className="stroke-text-04" height={size} width={size} />
    </div>
  );
}

export interface CustomAgentAvatarProps {
  name?: string;
  src?: string;
  iconName?: string;

  size?: number;
}

export default function CustomAgentAvatar({
  name,
  src,
  iconName,

  size = DEFAULT_AGENT_AVATAR_SIZE_PX,
}: CustomAgentAvatarProps) {
  if (src) {
    return (
      <div
        className="aspect-square rounded-full overflow-hidden relative"
        style={{ height: size, width: size }}
      >
        <Image
          alt={name || "Agent avatar"}
          src={src}
          fill
          className="object-cover object-center"
          sizes={`${size}px`}
        />
      </div>
    );
  }

  const iconConfig = iconName && iconMap[iconName];
  if (iconConfig) {
    const { Icon, className } = iconConfig;
    return (
      <SvgOctagonWrapper size={size}>
        <Icon
          className={cn("stroke-text-04", className)}
          style={{ width: size * 0.4, height: size * 0.4 }}
        />
      </SvgOctagonWrapper>
    );
  }

  // Display first letter of name if available, otherwise fall back to two-line-small icon
  const trimmedName = name?.trim();
  const firstLetter =
    trimmedName && trimmedName.length > 0
      ? trimmedName[0]!.toUpperCase()
      : undefined;
  const validFirstLetter = !!firstLetter && /^[a-zA-Z]$/.test(firstLetter);
  if (validFirstLetter) {
    return (
      <SvgOctagonWrapper size={size}>
        <Text as="span" style={{ fontSize: size * 0.5 }}>
          {firstLetter}
        </Text>
      </SvgOctagonWrapper>
    );
  }

  return (
    <SvgOctagonWrapper size={size}>
      <SvgTwoLineSmall
        className="stroke-text-04"
        style={{ width: size * 0.8, height: size * 0.8 }}
      />
    </SvgOctagonWrapper>
  );
}
