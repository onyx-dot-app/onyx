"use client";

import React, { useState } from "react";
import Text from "@/refresh-components/texts/Text";
import { cn, noProp } from "@/lib/utils";
import { SvgProps } from "@/icons";
import SvgChevronDownSmall from "@/icons/chevron-down-small";
import IconButton from "./IconButton";
import SvgX from "@/icons/x";

const buttonClasses = {
  open: [
    "bg-background-tint-inverted-03",
    "hover:bg-background-tint-inverted-04",
    "active:bg-background-tint-inverted-02",
  ],
  closed: [
    "bg-background-tint-01",
    "hover:bg-background-tint-02",
    "active:bg-background-tint-00",
  ],
};

const textClasses = {
  open: ["text-text-inverted-05"],
  closed: [
    "text-text-03",
    "group-hover/FilterButton:text-text-04",
    "group-active/FilterButton:text-text-05",
  ],
};

const iconClasses = {
  open: ["stroke-text-inverted-05"],
  closed: [
    "stroke-text-03",
    "group-hover/FilterButton:stroke-text-04",
    "group-active/FilterButton:stroke-text-05",
  ],
};

export interface FilterButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  // Button states:
  disabled?: boolean;
  open?: boolean;

  leftIcon: React.FunctionComponent<SvgProps>;
  onClear?: () => void;

  children?: string;
}

export default function FilterButton({
  open,

  leftIcon: LeftIcon,

  onClick,
  onClear,
  children,
  className,
  ...props
}: FilterButtonProps) {
  const [isHovered, setIsHovered] = useState(false);
  const state = open ? "open" : "closed";

  return (
    <button
      className={cn(
        "p-2 h-fit rounded-12 group/FilterButton flex flex-row items-center justify-center gap-1",
        buttonClasses[state],
        className
      )}
      onClick={onClick}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      {...props}
    >
      <div className="pr-0.5">
        <LeftIcon className={cn("w-[1rem] h-[1rem]", iconClasses[state])} />
      </div>

      <Text nowrap className={cn(textClasses[state])}>
        {children}
      </Text>
      <div className="pl-0">
        {open ? (
          <IconButton
            icon={SvgX}
            onClick={noProp(onClear)}
            secondary
            className="!p-0 !rounded-04"
          />
        ) : (
          <div className="w-[1rem] h-[1rem]">
            <SvgChevronDownSmall
              className={cn(
                "w-[1rem] h-[1rem] transition-transform duration-200 ease-in-out",
                iconClasses[state],
                isHovered && "-rotate-180"
              )}
            />
          </div>
        )}
      </div>
    </button>
  );
}
