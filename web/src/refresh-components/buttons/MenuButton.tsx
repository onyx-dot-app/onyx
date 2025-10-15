"use client";

import React from "react";
import Link from "next/link";
import { SvgProps } from "@/icons";
import { cn } from "@/lib/utils";
import Truncated from "@/refresh-components/texts/Truncated";

const textClasses = {
  main: ["text-text-03", "group-hover/NavigationTab:text-text-04"],
  danger: ["text-action-danger-05"],
} as const;

const iconClasses = {
  main: ["stroke-text-03", "group-hover/NavigationTab:stroke-text-04"],
  danger: ["stroke-action-danger-05"],
} as const;

export interface MenuButtonProps {
  // Button variants:
  danger?: boolean;

  // Button properties:
  onClick?: React.MouseEventHandler<HTMLDivElement>;
  href?: string;
  icon: React.FunctionComponent<SvgProps>;
  children?: string;
}

export default function MenuButton({
  danger,
  onClick,
  href,
  icon: Icon,
  children,
}: MenuButtonProps) {
  const variant = danger ? "danger" : "main";

  const innerContent = (
    <div
      className="flex flex-row justify-center items-center p-spacing-inline gap-spacing-inline rounded-08 cursor-pointer hover:bg-background-tint-03 group/NavigationTab w-full select-none bg-transparent"
      onClick={href ? undefined : onClick}
    >
      <div className="flex-1 h-[1.5rem] flex flex-row items-center px-spacing-inline py-spacing-inline-mini gap-spacing-interline justify-start">
        <div className="w-[1rem] h-[1rem]">
          <Icon className={cn("h-[1rem]", "w-[1rem]", iconClasses[variant])} />
        </div>
        {typeof children === "string" ? (
          <Truncated
            side="right"
            className={cn("text-left", textClasses[variant])}
          >
            {children}
          </Truncated>
        ) : (
          children
        )}
      </div>
    </div>
  );

  const content = innerContent;

  if (href)
    return (
      <Link href={href} className="w-full h-fit">
        {content}
      </Link>
    );

  return content;
}
