"use client";

import React, { useRef, useEffect, useState, useMemo } from "react";
import { cn } from "@/lib/utils";
import { SvgProps } from "@/icons";
import Text from "@/refresh-components/texts/Text";
import IconButton from "./IconButton";
import SvgX from "@/icons/x";
import SvgChevronDownSmall from "@/icons/chevron-down-small";

const MARGIN = 5;

const baseClassNames = (active?: boolean) =>
  ({
    enabled: [
      active && "bg-background-neutral-00",
      "hover:bg-background-tint-02",
    ],
    disabled: ["bg-background-neutral-02"],
  }) as const;

const iconClassNames = (active?: boolean) =>
  ({
    defaulted: {
      enabled: [
        active ? "stroke-text-05" : "stroke-text-03",
        "group-hover/SelectButton:stroke-text-04",
      ],
      disabled: ["stroke-text-01"],
    },
    action: {
      enabled: [active ? "stroke-action-link-05" : "stroke-text-03"],
      disabled: ["stroke-text-01"],
    },
  }) as const;

const textClassNames = (active?: boolean) =>
  ({
    defaulted: {
      enabled: [
        active ? "text-text-05" : "text-text-03",
        "group-hover/SelectButton:text-text-04",
      ],
      disabled: ["text-text-01"],
    },
    action: {
      enabled: [active ? "text-action-link-05" : "text-text-03"],
      disabled: ["text-text-01"],
    },
  }) as const;

export interface SelectButtonProps {
  // Button states
  active?: boolean;
  disabled?: boolean;
  folded?: boolean;

  // Variants
  action?: boolean;

  // Content
  children: string;
  leftIcon: React.FunctionComponent<SvgProps>;
  rightChevronIcon?: boolean;
  onClick?: () => void;
  className?: string;
}

export default function SelectButton({
  active,
  disabled,
  action,
  folded,
  children,
  leftIcon: LeftIcon,
  rightChevronIcon,
  onClick,
  className,
}: SelectButtonProps) {
  const variant = action ? "action" : "defaulted";
  const state = disabled ? "disabled" : "enabled";

  // Refs and state for measuring foldedContent width
  const measureRef = useRef<HTMLDivElement>(null);
  const [foldedContentWidth, setFoldedContentWidth] = useState<number>(0);
  const [hovered, setHovered] = useState<boolean>(false);
  const content = useMemo(
    () => (
      <div className="flex flex-row items-center justify-center">
        <Text
          className={cn(
            "whitespace-nowrap",
            textClassNames(active)[variant][state]
          )}
        >
          {children}
        </Text>

        {rightChevronIcon && (
          <SvgChevronDownSmall
            className={cn(
              "w-[1rem] h-[1rem] transition-all duration-300 ease-in-out",
              iconClassNames(active)[variant][state],
              active && "-rotate-180"
            )}
          />
        )}
      </div>
    ),
    [active, rightChevronIcon, children, variant, state]
  );
  useEffect(() => {
    if (measureRef.current) {
      const width = measureRef.current.clientWidth;
      setFoldedContentWidth(width);
    }
  }, [content]);

  return (
    <>
      {/* Hidden element for measuring the natural width of the content */}
      <div
        ref={measureRef}
        className="flex items-center w-auto h-fit absolute -left-[9999rem] opacity-0 pointer-events-none"
      >
        {content}
      </div>

      <button
        className={cn(
          baseClassNames(active)[state],
          "group/SelectButton flex items-center px-spacing-interline py-spacing-interline-mini rounded-12 h-fit w-fit",
          className
        )}
        onClick={disabled ? undefined : onClick}
        disabled={disabled}
        onMouseEnter={() => setHovered(true)}
        onMouseOver={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      >
        {/* Static icon component */}
        <LeftIcon
          className={cn(
            "w-[1rem] h-[1rem]",
            iconClassNames(active)[variant][state]
          )}
        />

        {/* Animation component */}
        <div
          className={cn(
            "flex items-center transition-all duration-300 ease-in-out overflow-hidden py-spacing-inline-mini",
            folded
              ? active || hovered
                ? "opacity-100"
                : "opacity-0"
              : "opacity-100"
          )}
          style={{
            width: folded
              ? active || hovered
                ? `${foldedContentWidth}px`
                : "0px"
              : `${foldedContentWidth}px`,
            margin: folded
              ? active || hovered
                ? `0px 0px 0px ${MARGIN}px`
                : "0px"
              : `0px 0px 0px ${MARGIN}px`,
          }}
        >
          {content}
        </div>
      </button>
    </>
  );
}
