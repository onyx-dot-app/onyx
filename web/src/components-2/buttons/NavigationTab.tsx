"use client";

import React, { useState } from "react";
import Link from "next/link";
import Text from "@/components-2/Text";
import { SvgProps } from "@/icons";
import SvgMoreHorizontal from "@/icons/more-horizontal";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import { IconButton } from "@/components-2/buttons/IconButton";
import Truncated from "@/components-2/Truncated";

const textClasses = (active: boolean | undefined) =>
  ({
    main: [
      active ? "text-text-04" : "text-text-03",
      "group-hover/NavigationTab:text-text-04",
    ],
    danger: ["text-action-danger-05"],
    highlight: [
      active ? "text-text-05" : "text-text-04",
      "group-hover/NavigationTab:text-text-05",
    ],
    lowlight: [
      active ? "text-text-03" : "text-text-02",
      "group-hover/NavigationTab:text-text-03",
    ],
  }) as const;

const iconClasses = (active: boolean | undefined) =>
  ({
    main: [
      active ? "stroke-text-04" : "stroke-text-03",
      "group-hover/NavigationTab:stroke-text-04",
    ],
    danger: ["stroke-action-danger-05"],
    highlight: [
      active ? "stroke-text-04" : "stroke-text-03",
      "group-hover/NavigationTab:stroke-text-04",
    ],
    lowlight: [
      active ? "stroke-text-03" : "stroke-text-02",
      "group-hover/NavigationTab:stroke-text-03",
    ],
  }) as const;

export interface NavigationTabProps {
  // Button states:
  folded?: boolean;
  active?: boolean;

  // Button variants:
  danger?: boolean;
  highlight?: boolean;
  lowlight?: boolean;

  // Button properties:
  onClick?: React.MouseEventHandler<HTMLDivElement>;
  href?: string;
  tooltip?: boolean;
  popover?: React.ReactNode;
  className?: string;
  icon: React.FunctionComponent<SvgProps>;
  children?: React.ReactNode;
}

export function NavigationTab({
  folded,
  active,

  danger,
  highlight,
  lowlight,

  onClick,
  href,
  tooltip,
  popover,
  className,
  icon: Icon,
  children,
}: NavigationTabProps) {
  // This is used to determine if the `PopoverTrigger` should be shown or not.
  // Do NOT use it for background colours.
  const [hovered, setHovered] = useState(false);
  const [kebabMenuOpen, setKebabMenuOpen] = useState(false);

  const variant = danger
    ? "danger"
    : highlight
      ? "highlight"
      : lowlight
        ? "lowlight"
        : "main";

  const innerContent = (
    <div
      className={cn(
        "flex flex-row justify-center items-center p-spacing-inline gap-spacing-inline rounded-08 cursor-pointer hover:bg-background-tint-03 group/NavigationTab",
        folded ? "w-min" : "w-full",
        active ? "bg-background-tint-00" : "bg-transparent",
        className
      )}
      onMouseEnter={() => setHovered(true)}
      onMouseOver={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onClick={href ? undefined : onClick}
    >
      <div
        className={cn(
          "flex-1 h-[1.8rem] flex flex-row items-center p-spacing-inline gap-spacing-interline",
          folded ? "justify-center" : "justify-start"
        )}
      >
        <div className="w-[1.2rem] h-[1.2rem]">
          <Icon
            className={cn(
              "h-[1.2rem] w-[1.2rem]",
              iconClasses(active)[variant]
            )}
          />
        </div>
        {!folded &&
          (typeof children === "string" ? (
            <Truncated
              side="right"
              offset={40}
              className={cn("text-left", textClasses(active)[variant])}
            >
              {children}
            </Truncated>
          ) : (
            children
          ))}
      </div>
      {!folded && popover && (active || hovered || kebabMenuOpen) && (
        <Popover onOpenChange={setKebabMenuOpen}>
          <PopoverTrigger asChild onClick={(event) => event.stopPropagation()}>
            <IconButton
              icon={SvgMoreHorizontal}
              internal
              active={kebabMenuOpen}
            />
          </PopoverTrigger>
          <PopoverContent
            align="end"
            side="right"
            avoidCollisions
            sideOffset={8}
          >
            {popover}
          </PopoverContent>
        </Popover>
      )}
    </div>
  );

  const content =
    folded && tooltip && typeof children === "string" ? (
      <Tooltip>
        <TooltipTrigger asChild>{innerContent}</TooltipTrigger>
        <TooltipContent align="center" side="right">
          <Text inverted secondaryBody>
            {children}
          </Text>
        </TooltipContent>
      </Tooltip>
    ) : (
      innerContent
    );

  if (href) return <Link href={href}>{content}</Link>;

  return content;
}
