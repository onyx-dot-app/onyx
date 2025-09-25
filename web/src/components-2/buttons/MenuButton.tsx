"use client";

import React from "react";
import Link from "next/link";
import Text from "@/components-2/Text";
import { SvgProps } from "@/icons";

export interface MenuButtonProps {
  children?: string;
  onClick?: () => void;
  href?: string;
  icon?: React.FunctionComponent<SvgProps>;
  danger?: boolean;
}

export function MenuButton({
  children,
  onClick,
  href,
  icon: Icon,
  danger,
}: MenuButtonProps) {
  const content = (
    <button
      className="flex p-padding-button gap-spacing-interline rounded-08 hover:bg-background-tint-02 w-full"
      onClick={(event) => {
        event.stopPropagation();
        onClick?.();
      }}
    >
      {Icon && (
        <Icon
          className={`h-[1.2rem] min-w-[1.2rem] stroke-text-04 ${danger && "!stroke-action-danger-05"}`}
        />
      )}
      <Text text04 className={danger ? "!text-action-danger-05" : undefined}>
        {children}
      </Text>
    </button>
  );

  if (!href) return content;

  return <Link href={href}>{content}</Link>;
}
