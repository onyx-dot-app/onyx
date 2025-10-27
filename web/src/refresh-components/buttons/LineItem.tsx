"use client";

import React from "react";
import Text from "@/refresh-components/texts/Text";
import { cn } from "@/lib/utils";
import { SvgProps } from "@/icons";
import Truncated from "@/refresh-components/texts/Truncated";
import Link from "next/link";

interface LineItemProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  icon?: React.FunctionComponent<SvgProps>;
  description?: string;
  children?: string | React.ReactNode;
  strikethrough?: boolean;
  rightChildren?: React.ReactNode;
  onClick?: React.MouseEventHandler<HTMLButtonElement>;
  href?: string;
}

export default function LineItem({
  icon: Icon,
  description,
  children,
  strikethrough,
  rightChildren,
  onClick,
  href,
}: LineItemProps) {
  const content = (
    <button
      type="button"
      className={cn(
        "flex flex-col w-full justify-center items-start p-2 hover:bg-background-tint-02 rounded-08 group/LineItem"
      )}
      onClick={onClick}
    >
      <div className="flex flex-row items-center justify-start w-full gap-2">
        {Icon && (
          <div className="h-[1rem] w-[1rem]">
            <Icon className="h-[1rem] w-[1rem] stroke-text-03" />
          </div>
        )}
        {typeof children === "string" ? (
          <Truncated
            mainUiMuted
            text04
            className={cn(
              "text-left w-full",
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
