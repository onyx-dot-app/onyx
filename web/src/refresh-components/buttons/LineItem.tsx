"use client";

import React from "react";
import Text from "@/refresh-components/texts/Text";
import { cn } from "@/lib/utils";
import { SvgProps } from "@/icons";
import Truncated from "@/refresh-components/texts/Truncated";
import Link from "next/link";

type Variant = keyof typeof buttonClassNames;

const buttonClassNames = {
  main: {
    normal: ["bg-transparent", "hover:bg-background-tint-02"],
    emphasized: ["bg-action-link-01", "hover:bg-background-tint-02"],
  },
  forced: {
    normal: ["bg-action-link-01", "hover:bg-background-tint-02"],
    emphasized: ["bg-action-link-01", "hover:bg-background-tint-02"],
  },
  strikethrough: {
    normal: ["bg-transparent", "hover:bg-background-tint-02"],
    emphasized: ["bg-transparent", "hover:bg-background-tint-02"],
  },
  danger: {
    normal: ["bg-transparent", "hover:bg-background-tint-02"],
    emphasized: ["bg-status-error-01", "hover:bg-background-tint-02"],
  },
};

const textClassNames = {
  main: ["text-text-04"],
  forced: ["text-action-link-05"],
  strikethrough: ["text-text-02", "line-through", "decoration-2"],
  danger: ["text-status-error-05"],
};

const iconClassNames = {
  main: ["stroke-text-03"],
  forced: ["stroke-action-link-05"],
  strikethrough: ["stroke-text-03"],
  danger: ["stroke-status-error-05"],
};

export interface LineItemProps extends React.HTMLAttributes<HTMLButtonElement> {
  // Button variants (mutually exclusive)
  forced?: boolean;
  strikethrough?: boolean;
  danger?: boolean;

  // Modifier
  emphasized?: boolean;

  icon?: React.FunctionComponent<SvgProps>;
  description?: string;
  rightChildren?: React.ReactNode;
  href?: string;
}

export default function LineItem({
  forced,
  strikethrough,
  danger,

  emphasized,

  icon: Icon,
  description,
  className,
  children,
  rightChildren,
  href,
  ...props
}: LineItemProps) {
  // Determine variant (mutually exclusive, with priority order)
  const variant: Variant = forced
    ? "forced"
    : strikethrough
      ? "strikethrough"
      : danger
        ? "danger"
        : "main";

  const emphasisKey = emphasized ? "emphasized" : "normal";

  const content = (
    <button
      className={cn(
        "flex flex-col w-full justify-center items-start p-2 rounded-08 group/LineItem",
        buttonClassNames[variant][emphasisKey],
        className
      )}
      type="button"
      {...props}
    >
      <div className="flex flex-row items-center justify-start w-full gap-2">
        {Icon && (
          <div className="h-[1rem] min-w-[1rem]">
            <Icon
              className={cn("h-[1rem] w-[1rem]", iconClassNames[variant])}
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
    </button>
  );

  if (!href) return content;
  return <Link href={href}>{content}</Link>;
}
