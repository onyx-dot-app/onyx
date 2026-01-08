"use client";

import { cn } from "@/lib/utils";
import type { IconProps } from "@opal/types";
import Text from "@/refresh-components/texts/Text";
import Image from "next/image";
import { DEFAULT_AGENT_AVATAR_SIZE_PX } from "@/lib/constants";
import {
  SvgActivitySmall,
  SvgAudioEqSmall,
  SvgBarChartSmall,
  SvgBooksLineSmall,
  SvgBooksStackSmall,
  SvgCheckSmall,
  SvgClockHandsSmall,
  SvgFileSmall,
  SvgHashSmall,
  SvgImageSmall,
  SvgInfoSmall,
  SvgMusicSmall,
  SvgOnyxOctagon,
  SvgPenSmall,
  SvgQuestionMarkSmall,
  SvgSearchSmall,
  SvgSlidersSmall,
  SvgTerminalSmall,
  SvgTextLinesSmall,
  SvgTwoLineSmall,
} from "@opal/icons";

interface IconConfig {
  Icon: React.FunctionComponent<IconProps>;
  className?: string;
}

export const agentAvatarIconMap: Record<string, IconConfig> = {
  Info: { Icon: SvgInfoSmall, className: "stroke-theme-primary-05" },
  QuestionMark: {
    Icon: SvgQuestionMarkSmall,
    className: "stroke-theme-primary-05",
  },

  // blue
  TextLines: { Icon: SvgTextLinesSmall, className: "stroke-theme-blue-05" },
  Pen: { Icon: SvgPenSmall, className: "stroke-theme-blue-05" },
  ClockHands: { Icon: SvgClockHandsSmall, className: "stroke-theme-blue-05" },
  Hash: { Icon: SvgHashSmall, className: "stroke-theme-blue-05" },

  // green
  Search: { Icon: SvgSearchSmall, className: "stroke-theme-green-05" },
  Check: { Icon: SvgCheckSmall, className: "stroke-theme-green-05" },
  BarChart: { Icon: SvgBarChartSmall, className: "stroke-theme-green-05" },
  Activity: { Icon: SvgActivitySmall, className: "stroke-theme-green-05" },

  // purple
  File: { Icon: SvgFileSmall, className: "stroke-theme-purple-05" },
  Image: { Icon: SvgImageSmall, className: "stroke-theme-purple-05" },
  BooksStack: { Icon: SvgBooksStackSmall, className: "stroke-theme-purple-05" },
  BooksLine: { Icon: SvgBooksLineSmall, className: "stroke-theme-purple-05" },

  // orange
  Terminal: { Icon: SvgTerminalSmall, className: "stroke-theme-orange-04" },
  Sliders: { Icon: SvgSlidersSmall, className: "stroke-theme-orange-04" },

  // amber
  AudioEq: { Icon: SvgAudioEqSmall, className: "stroke-theme-amber-04" },
  Music: { Icon: SvgMusicSmall, className: "stroke-theme-amber-04" },
};

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

  const iconConfig = iconName && agentAvatarIconMap[iconName];
  if (iconConfig) {
    const { Icon, className } = iconConfig;
    const multiplier = 0.7;
    return (
      <SvgOctagonWrapper size={size}>
        <Icon
          className={cn("stroke-text-04", className)}
          style={{ width: size * multiplier, height: size * multiplier }}
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
