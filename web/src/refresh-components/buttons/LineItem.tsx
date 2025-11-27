"use client";

import React from "react";
import Text from "@/refresh-components/texts/Text";
import { cn } from "@/lib/utils";
import { SvgProps } from "@/icons";
import Truncated from "@/refresh-components/texts/Truncated";
import Link from "next/link";

const buttonClassNames = {
  main: {
    normal: "line-item-button-main",
    emphasized: "line-item-button-main-emphasized",
  },
  strikethrough: {
    normal: "line-item-button-strikethrough",
    emphasized: "line-item-button-strikethrough-emphasized",
  },
  danger: {
    normal: "line-item-button-danger",
    emphasized: "line-item-button-danger-emphasized",
  },
} as const;

const textClassNames = {
  main: "line-item-text-main",
  strikethrough: "line-item-text-strikethrough",
  danger: "line-item-text-danger",
} as const;

const iconClassNames = {
  main: "line-item-icon-main",
  strikethrough: "line-item-icon-strikethrough",
  danger: "line-item-icon-danger",
} as const;

export interface LineItemProps extends React.HTMLAttributes<HTMLButtonElement> {
  // line-item variants
  strikethrough?: boolean;
  danger?: boolean;

  // modifier (makes the background more pronounced when selected).
  emphasized?: boolean;

  selected?: boolean;
  icon?: React.FunctionComponent<SvgProps>;
  description?: string;
  rightChildren?: React.ReactNode;
  href?: string;
}

/**
 * LineItem Component
 *
 * A versatile menu item button component designed for use in dropdowns, sidebars, and menus.
 * Supports icons, descriptions, and multiple visual states.
 *
 * @example
 * ```tsx
 * // Basic usage
 * <LineItem icon={SvgUser}>Profile Settings</LineItem>
 *
 * // With selection state
 * <LineItem icon={SvgCheck} selected>Active Item</LineItem>
 *
 * // With emphasis (highlighted background)
 * <LineItem icon={SvgFolder} selected emphasized>
 *   Selected Folder
 * </LineItem>
 *
 * // Danger variant
 * <LineItem icon={SvgTrash} danger>Delete Account</LineItem>
 *
 * // With description
 * <LineItem icon={SvgSettings} description="Manage your account settings">
 *   Settings
 * </LineItem>
 *
 * // With right content
 * <LineItem icon={SvgKey} rightChildren={<Text text03>⌘K</Text>}>
 *   Keyboard Shortcuts
 * </LineItem>
 *
 * // As a link
 * <LineItem icon={SvgHome} href="/dashboard">Dashboard</LineItem>
 *
 * // Strikethrough (disabled/deprecated items)
 * <LineItem icon={SvgArchive} strikethrough>
 *   Archived Feature
 * </LineItem>
 * ```
 *
 * @remarks
 * - Variants are mutually exclusive: only one of `strikethrough` or `danger` should be used
 * - The `selected` prop modifies text/icon colors for `main` and `danger` variants
 * - The `emphasized` prop adds background colors when combined with `selected`
 * - The component automatically adds a `data-selected="true"` attribute for custom styling
 */
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
          buttonClassNames[variant][emphasisKey],
          className
        )}
        type="button"
        data-selected={selected}
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
);
LineItem.displayName = "LineItem";

export default LineItem;
