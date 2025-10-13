"use client";

import React from "react";
import { SvgProps } from "@/icons";
import { cn } from "@/lib/utils";
import {
  TruncatedContent,
  TruncatedProvider,
  TruncatedTrigger,
} from "../texts/Truncated";
import Text from "../texts/Text";
import SimpleTooltip from "../SimpleTooltip";
import Link from "next/link";

const textClasses = (active: boolean | undefined) =>
  ({
    defaulted: [
      active ? "text-text-04" : "text-text-03",
      "group-hover/SidebarTab:text-text-04",
    ],
    lowlight: [
      active ? "text-text-03" : "text-text-02",
      "group-hover/SidebarTab:text-text-03",
    ],
  }) as const;

const iconClasses = (active: boolean | undefined) =>
  ({
    defaulted: [
      active ? "stroke-text-04" : "stroke-text-03",
      "group-hover/SidebarTab:stroke-text-04",
    ],
    lowlight: [
      active ? "stroke-text-03" : "stroke-text-02",
      "group-hover/SidebarTab:stroke-text-03",
    ],
  }) as const;

export interface SidebarTabProps {
  // Button states:
  folded?: boolean;
  active?: boolean;
  lowlight?: boolean;

  // Button properties:
  onClick?: React.MouseEventHandler<HTMLDivElement>;
  href?: string;
  className?: string;
  leftIcon?: React.FunctionComponent<SvgProps>;
  rightChildren?: React.ReactNode;
  children?: React.ReactNode;
}

export default function SidebarTab({
  folded,
  active,
  lowlight,

  onClick,
  href,
  className,
  leftIcon: LeftIcon,
  rightChildren,
  children,
}: SidebarTabProps) {
  const variant = lowlight ? "lowlight" : "defaulted";

  const content = (
    <div
      className={cn(
        "flex flex-row justify-center items-center p-spacing-interline-mini gap-spacing-inline rounded-08 cursor-pointer hover:bg-background-tint-03 group/SidebarTab w-full select-none",
        active ? "bg-background-tint-00" : "bg-transparent",
        className
      )}
      onClick={onClick}
    >
      <div
        className={cn(
          "flex-1 h-[1.5rem] flex flex-row items-center px-spacing-inline py-spacing-inline-mini gap-spacing-interline",
          folded ? "justify-center" : "justify-start"
        )}
      >
        {LeftIcon && (
          <div className="w-[1rem] h-[1rem] flex flex-col items-center justify-center">
            <LeftIcon
              className={cn(
                "h-[1rem]",
                "w-[1rem]",
                iconClasses(active)[variant]
              )}
            />
          </div>
        )}
        {!folded &&
          (typeof children === "string" ? (
            <TruncatedTrigger className={cn(textClasses(active)[variant])}>
              {children}
            </TruncatedTrigger>
          ) : (
            children
          ))}
      </div>
      {!folded && rightChildren}
    </div>
  );

  const linkedContent = href ? <Link href={href}>{content}</Link> : content;

  if (typeof children !== "string") return linkedContent;

  return folded ? (
    <SimpleTooltip tooltip={children}>{linkedContent}</SimpleTooltip>
  ) : (
    <TruncatedProvider>
      {linkedContent}

      <TruncatedContent>
        <Text inverted>{children}</Text>
      </TruncatedContent>
    </TruncatedProvider>
  );
}
