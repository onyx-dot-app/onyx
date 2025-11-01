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

const textClassNames = (forced?: boolean) =>
  forced ? ["text-action-link-05"] : ["text-text-04"];

const iconClassNames = (forced?: boolean) =>
  forced ? ["stroke-action-link-05"] : ["stroke-text-03"];

export interface LineItemProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  // Button variants
  forced?: boolean;
  heavyForced?: boolean;
  strikethrough?: boolean;

  icon?: React.FunctionComponent<SvgProps>;
  description?: string;
  children?: string | React.ReactNode;
  rightChildren?: React.ReactNode;
  onClick?: React.MouseEventHandler<HTMLButtonElement>;
  href?: string;
}

export default function LineItem({
  forced,
  heavyForced,
  strikethrough,

  icon: Icon,
  description,
  children,
  rightChildren,
  onClick,
  href,
}: LineItemProps) {
  const content = (
    <button
      type="button"
      className={cn(
        "flex flex-col w-full justify-center items-start p-2 rounded-08 group/LineItem",
        buttonClassNames(heavyForced)
      )}
      onClick={onClick}
    >
      <div className="flex flex-row items-center justify-start w-full gap-2">
        {Icon && (
          <div className="h-[1rem] w-[1rem]">
            <Icon
              className={cn(
                "h-[1rem] w-[1rem]",
                iconClassNames(forced || heavyForced)
              )}
            />
          </div>
        )}
        {typeof children === "string" ? (
          <Truncated
            mainUiMuted
            text04
            className={cn(
              "text-left w-full",
              textClassNames(forced || heavyForced),
              strikethrough && "line-through decoration-[1.5px]"
            )}
          >
            {children}
          </Truncated>
        ) : (
          children
        )}
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
    </button>
  );

  if (!href) return content;
  return <Link href={href}>{content}</Link>;
}
