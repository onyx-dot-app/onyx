"use client";

import { cn } from "@/lib/utils";
import SvgCheck from "@/icons/check";
import SvgCode from "@/icons/code";
import SvgTwoLineSmall from "@/icons/two-line-small";
import SvgOnyxOctagon from "@/icons/onyx-octagon";
import SvgSearch from "@/icons/search";
import { SvgProps } from "@/icons";

interface IconConfig {
  Icon: React.FunctionComponent<SvgProps>;
  className?: string;
}

const iconMap: Record<string, IconConfig> = {
  search: { Icon: SvgSearch, className: "stroke-green-500" },
  check: { Icon: SvgCheck, className: "stroke-green-500" },
  code: { Icon: SvgCode, className: "stroke-orange-500" },
};

interface SvgOctagonWrapperProps {
  size: number;
  children: React.ReactNode;
}

function SvgOctagonWrapper({ size, children }: SvgOctagonWrapperProps) {
  return (
    <div
      className="relative flex flex-col items-center justify-center"
      style={{ width: size, height: size }}
    >
      <SvgOnyxOctagon
        className="absolute inset-0 stroke-text-04"
        style={{ width: size, height: size }}
      />
      {children}
    </div>
  );
}

export interface CustomAgentIconProps {
  name?: string;
  src?: string;
  iconName?: string;

  size?: number;
}

export default function CustomAgentIcon({
  name,
  src,
  iconName,

  size = 18,
}: CustomAgentIconProps) {
  if (src) {
    return (
      <img
        alt={name}
        src={src}
        loading="lazy"
        className="rounded-full object-cover object-center"
        width={size}
        height={size}
      />
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
  if (firstLetter) {
    return (
      <SvgOctagonWrapper size={size}>
        <span
          className="text-text-04 font-bold"
          style={{ fontSize: size * 0.5 }}
        >
          {firstLetter}
        </span>
      </SvgOctagonWrapper>
    );
  }

  return (
    <SvgOctagonWrapper size={size}>
      <SvgTwoLineSmall className="stroke-text-04 h-8 w-8" />
    </SvgOctagonWrapper>
  );
}
