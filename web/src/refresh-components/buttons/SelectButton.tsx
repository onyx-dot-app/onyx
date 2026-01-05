"use client";

import React, { useState, useMemo } from "react";
import { cn } from "@/lib/utils";
import type { IconProps } from "@opal/types";
import Text from "@/refresh-components/texts/Text";
import { SvgChevronDownSmall } from "@opal/icons";
import { useContentSize } from "@/hooks/useContentSize";

const MARGIN = 5;

const baseClassNames = (engaged?: boolean, transient?: boolean) =>
  ({
    main: {
      enabled: [
        "bg-transparent",
        "hover:bg-background-tint-02",
        transient && "bg-background-tint-02",
        "active:bg-background-tint-00",
      ],
      disabled: ["bg-background-neutral-02"],
    },
    action: {
      enabled: [
        engaged ? "bg-action-link-01" : "bg-transparent",
        engaged ? "hover:bg-action-link-01" : "hover:bg-background-tint-02",
        "active:bg-background-tint-00",
      ],
      disabled: ["bg-background-neutral-02"],
    },
  }) as const;

const iconClassNames = (engaged?: boolean, transient?: boolean) =>
  ({
    main: {
      enabled: [
        "stroke-text-03",
        "group-hover/SelectButton:stroke-text-04",
        transient && "stroke-text-04",
        "group-active/SelectButton:stroke-text-05",
      ],
      disabled: ["stroke-text-02"],
    },
    action: {
      enabled: [
        engaged ? "stroke-action-link-05" : "stroke-text-03",
        engaged
          ? "group-hover/SelectButton:stroke-action-link-05"
          : "group-hover/SelectButton:stroke-text-04",
        engaged
          ? "group-active/SelectButton:stroke-action-link-06"
          : "group-active/SelectButton:stroke-text-05",
      ],
      disabled: ["stroke-action-link-03"],
    },
  }) as const;

const textClassNames = (engaged?: boolean, transient?: boolean) =>
  ({
    main: {
      enabled: [
        "text-text-03",
        "group-hover/SelectButton:text-text-04",
        transient && "text-text-04",
        "group-active/SelectButton:text-text-05",
      ],
      disabled: ["text-text-01"],
    },
    action: {
      enabled: [
        engaged ? "text-action-link-05" : "text-text-03",
        engaged
          ? "group-hover/SelectButton:text-action-link-05"
          : "group-hover/SelectButton:text-text-04",
        engaged
          ? "group-active/SelectButton:text-action-link-06"
          : "group-active/SelectButton:text-text-05",
      ],
      disabled: ["stroke-action-link-03"],
    },
  }) as const;

export interface SelectButtonProps {
  // Button variants
  main?: boolean;
  action?: boolean;

  // Button states
  transient?: boolean;
  engaged?: boolean;
  disabled?: boolean;
  folded?: boolean;

  // Content
  children: string;
  leftIcon?: React.FunctionComponent<IconProps>;
  rightIcon?: React.FunctionComponent<IconProps>;
  rightChevronIcon?: boolean;
  onClick?: () => void;
  className?: string;
}

export default function SelectButton({
  main,
  action,

  transient,
  engaged,
  disabled,
  folded,

  children,
  leftIcon: LeftIcon,
  rightIcon: RightIcon,
  rightChevronIcon,
  onClick,
  className,
}: SelectButtonProps) {
  const hasRightIcon = !!RightIcon;
  const hasLeftIcon = !!LeftIcon;
  const variant = main ? "main" : action ? "action" : "main";
  const state = disabled ? "disabled" : "enabled";

  // Refs and state for measuring foldedContent width
  const [hovered, setHovered] = useState<boolean>(false);

  // Memoize class name invocations
  const baseClasses = useMemo(
    () => baseClassNames(engaged, transient)[variant][state],
    [engaged, transient, variant, state]
  );
  const iconClasses = useMemo(
    () => iconClassNames(engaged, transient)[variant][state],
    [engaged, transient, variant, state]
  );
  const textClasses = useMemo(
    () => textClassNames(engaged, transient)[variant][state],
    [engaged, transient, variant, state]
  );

  const content = useMemo(
    () => (
      <div className="flex flex-row items-center justify-center">
        <Text as="p" className={cn("whitespace-nowrap", textClasses)}>
          {children}
        </Text>

        {rightChevronIcon && (
          <SvgChevronDownSmall
            className={cn(
              "w-[1rem] h-[1rem] transition-all duration-300 ease-in-out",
              iconClasses,
              transient && "-rotate-180"
            )}
          />
        )}
      </div>
    ),
    [textClasses, iconClasses, rightChevronIcon, children, transient]
  );
  const [measureRef, { width: foldedContentWidth }] = useContentSize([content]);

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
          baseClasses,
          "group/SelectButton flex items-center px-2 py-2 rounded-12 h-fit w-fit",
          className
        )}
        onClick={disabled ? undefined : onClick}
        disabled={disabled}
        onMouseEnter={() => setHovered(true)}
        onMouseOver={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      >
        {/* Left icon */}
        {hasLeftIcon && LeftIcon && (
          <LeftIcon className={cn("w-[1rem] h-[1rem]", iconClasses)} />
        )}

        {/* Animation component */}
        <div
          className={cn(
            "flex items-center transition-all duration-300 ease-in-out overflow-hidden",
            folded
              ? engaged || transient || hovered
                ? "opacity-100"
                : "opacity-0"
              : "opacity-100"
          )}
          style={{
            width: folded
              ? engaged || transient || hovered
                ? `${foldedContentWidth}px`
                : "0px"
              : `${foldedContentWidth}px`,
            margin: folded
              ? engaged || transient || hovered
                ? hasRightIcon
                  ? `0px ${MARGIN}px 0px 0px`
                  : `0px 0px 0px ${MARGIN}px`
                : "0px"
              : hasRightIcon
                ? `0px ${MARGIN}px 0px 0px`
                : `0px 0px 0px ${MARGIN}px`,
          }}
        >
          {content}
        </div>

        {/* Right icon */}
        {hasRightIcon && RightIcon && (
          <RightIcon className={cn("w-[1rem] h-[1rem]", iconClasses)} />
        )}
      </button>
    </>
  );
}
