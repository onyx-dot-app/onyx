"use client";

import React from "react";
import Text from "@/refresh-components/texts/Text";
import { cn } from "@/lib/utils";
import { SvgProps } from "@/icons";
import Truncated from "@/refresh-components/texts/Truncated";
import Link from "next/link";

const buttonClassNames = (heavyForced?: boolean) =>
  heavyForced
    ? ["bg-action-link-01", "hover:bg-background-tint-02"]
    : ["bg-transparent", "hover:bg-background-tint-02"];

const textClassNames = {
  main: ["text-text-04"],
  forced: ["text-action-link-05"],
  strikeThrough: ["text-text-02", "line-through decoration-2"],
};

const iconClassNames = (forced?: boolean) =>
  forced ? ["stroke-action-link-05"] : ["stroke-text-03"];

export interface LineItemProps extends React.HTMLAttributes<HTMLDivElement> {
  // Button variants
  main?: boolean;
  forced?: boolean;
  heavyForced?: boolean;
  strikethrough?: boolean;

  icon?: React.FunctionComponent<SvgProps>;
  description?: string;
  children?: string;
  rightChildren?: React.ReactNode;
  onClick?: React.MouseEventHandler<HTMLDivElement>;
  href?: string;
}

export default function LineItem({
  main,
  forced,
  heavyForced,
  strikethrough,

  icon: Icon,
  description,
  className,
  children,
  rightChildren,
  onClick,
  href,
  ...props
}: LineItemProps) {
  const variant = main
    ? "main"
    : strikethrough
      ? "strikeThrough"
      : forced || heavyForced
        ? "forced"
        : "main";

  const content = (
    <div
      className={cn(
        "flex flex-col w-full justify-center items-start p-2 rounded-08 group/LineItem cursor-pointer",
        buttonClassNames(heavyForced),
        className
      )}
      onClick={onClick}
      {...props}
    >
      <div className="flex flex-row items-center justify-start w-full gap-2">
        {Icon && (
          <div className="h-[1rem] min-w-[1rem] bg-red">
            <Icon
              className={cn(
                "h-[1rem] w-[1rem]",
                iconClassNames(forced || heavyForced)
              )}
            />
          </div>
        )}
        <Truncated
          mainUiMuted
          text04
          className={cn("text-left w-full", textClassNames[variant])}
        >
          {children}
        </Truncated>
        {rightChildren}
      </div>
      {description && (
        <div className="flex flex-row">
          {Icon && (
            <>
              <div className="w-[1rem]" />
              <div className="w-2" />
            </>
          )}

          <Text secondaryBody text03>
            {description}
          </Text>
        </div>
      )}
    </div>
  );

  if (!href) return content;
  return <Link href={href}>{content}</Link>;
}
