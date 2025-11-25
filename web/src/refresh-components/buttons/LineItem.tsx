"use client";

import React from "react";
import Text from "@/refresh-components/texts/Text";
import { cn } from "@/lib/utils";
import { SvgProps } from "@/icons";
import Truncated from "@/refresh-components/texts/Truncated";
import Link from "next/link";

const buttonClassNames = (selected?: boolean) =>
  ({
    main: {
      normal: ["bg-transparent", "hover:bg-background-tint-02"],
      emphasized: [
        selected ? "bg-action-link-01" : "bg-transparent",
        "hover:bg-background-tint-02",
      ],
    },
    strikethrough: {
      normal: ["bg-transparent", "hover:bg-background-tint-02"],
      emphasized: ["bg-transparent", "hover:bg-background-tint-02"],
    },
    danger: {
      normal: ["bg-transparent", "hover:bg-background-tint-02"],
      emphasized: [
        selected ? "bg-status-error-01" : "bg-transparent",
        "hover:bg-background-tint-02",
      ],
    },
  }) as const;

const getTextClassNames = (selected?: boolean) =>
  ({
    main: selected ? ["text-action-link-05"] : ["text-text-04"],
    strikethrough: ["text-text-02", "line-through", "decoration-2"],
    danger: selected ? ["text-action-link-05"] : ["text-status-error-05"],
  }) as const;

const getIconClassNames = (selected?: boolean) =>
  ({
    main: selected ? ["stroke-action-link-05"] : ["stroke-text-03"],
    strikethrough: ["stroke-text-03"],
    danger: selected ? ["stroke-action-link-05"] : ["stroke-status-error-05"],
  }) as const;

export interface LineItemProps extends React.HTMLAttributes<HTMLButtonElement> {
  selected?: boolean;

  // line-item variants
  strikethrough?: boolean;
  danger?: boolean;

  // modifies the line-item to be more "pronounced" (i.e., modifies the background colour to be more highlighted).
  emphasized?: boolean;

  icon?: React.FunctionComponent<SvgProps>;
  description?: string;
  rightChildren?: React.ReactNode;
  href?: string;
}
const LineItem = React.forwardRef<HTMLButtonElement, LineItemProps>(
  (
    {
      selected,

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
    },
    ref
  ) => {
    // Determine variant (mutually exclusive, with priority order)
    const variant = strikethrough
      ? "strikethrough"
      : danger
        ? "danger"
        : "main";

    const emphasisKey = emphasized ? "emphasized" : "normal";

    const content = (
      <button
        ref={ref}
        className={cn(
          "flex flex-col w-full justify-center items-start p-2 rounded-08 group/LineItem",
          buttonClassNames(selected)[variant][emphasisKey],
          className
        )}
        type="button"
        data-selected={selected ? "true" : undefined}
        {...props}
      >
        <div className="flex flex-row items-center justify-start w-full gap-2">
          {Icon && (
            <div className="h-[1rem] min-w-[1rem]">
              <Icon
                className={cn(
                  "h-[1rem] w-[1rem]",
                  getIconClassNames(selected)[variant]
                )}
              />
            </div>
          )}
          <Truncated
            mainUiMuted
            text04
            className={cn(
              "text-left w-full",
              getTextClassNames(selected)[variant]
            )}
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
);
LineItem.displayName = "LineItem";

export default LineItem;
