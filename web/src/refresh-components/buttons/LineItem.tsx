"use client";

import React from "react";
import Text from "@/refresh-components/texts/Text";
import { cn } from "@/lib/utils";
import { SvgProps } from "@/icons";
import Truncated from "@/refresh-components/texts/Truncated";

interface LineItemProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  icon?: React.FunctionComponent<SvgProps>;
  description?: string;
  children?: string | React.ReactNode;
  rightChildren?: React.ReactNode;
  onClick?: React.MouseEventHandler<HTMLButtonElement>;
}

export default function LineItem({
  icon: Icon,
  description,
  children,
  rightChildren,
  onClick,
}: LineItemProps) {
  return (
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
          <Truncated mainUiMuted text04 className="text-left w-full">
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
}
