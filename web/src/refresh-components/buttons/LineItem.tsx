import React from "react";
import { cn } from "@/lib/utils";
import type { IconProps } from "@opal/types";
import Truncated from "@/refresh-components/texts/Truncated";
import Link from "next/link";
import type { Route } from "next";
import { Section } from "@/layouts/general-layouts";
import { WithoutStyles } from "@/types";

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
  action: {
    normal: "line-item-button-action",
    emphasized: "line-item-button-action-emphasized",
  },
  muted: {
    normal: "line-item-button-muted",
    emphasized: "line-item-button-muted-emphasized",
  },
  skeleton: {
    normal: "line-item-button-skeleton",
    emphasized: "line-item-button-skeleton-emphasized",
  },
} as const;

const textClassNames = {
  main: "line-item-text-main",
  strikethrough: "line-item-text-strikethrough",
  danger: "line-item-text-danger",
  action: "line-item-text-action",
  muted: "line-item-text-muted",
  skeleton: "line-item-text-skeleton",
} as const;

const iconClassNames = {
  main: "line-item-icon-main",
  strikethrough: "line-item-icon-strikethrough",
  danger: "line-item-icon-danger",
  action: "line-item-icon-action",
  muted: "line-item-icon-muted",
  skeleton: "line-item-icon-skeleton",
} as const;

export interface LineItemProps
  extends Omit<
    WithoutStyles<React.HTMLAttributes<HTMLDivElement>>,
    "children"
  > {
  // line-item variants
  strikethrough?: boolean;
  danger?: boolean;
  action?: boolean;
  muted?: boolean;
  skeleton?: boolean;

  // modifier (makes the background more pronounced when selected).
  emphasized?: boolean;

  selected?: boolean;
  icon?: React.FunctionComponent<IconProps>;
  description?: string;
  rightChildren?: React.ReactNode;
  href?: string;
  ref?: React.Ref<HTMLDivElement>;
  children?: React.ReactNode;
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
 * <LineItem icon={SvgKey} rightChildren={<Text as="p" text03>⌘K</Text>}>
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
 *
 * // Muted variant (less prominent items)
 * <LineItem icon={SvgFolder} muted>
 *   Secondary Item
 * </LineItem>
 * ```
 *
 * @remarks
 * - Variants are mutually exclusive: only one of `strikethrough`, `danger`, `action`, `muted`, or `skeleton` should be used
 * - The `selected` prop modifies text/icon colors for `main` and `danger` variants
 * - The `emphasized` prop adds background colors when combined with `selected`
 * - The component automatically adds a `data-selected="true"` attribute for custom styling
 */
export default function LineItem({
  selected,
  strikethrough,
  danger,
  action,
  muted,
  skeleton,
  emphasized,
  icon: Icon,
  description,
  children,
  rightChildren,
  href,
  ref,
  ...props
}: LineItemProps) {
  // Determine variant (mutually exclusive, with priority order: strikethrough > danger > action > muted > main)
  const variant = strikethrough
    ? "strikethrough"
    : danger
      ? "danger"
      : action
        ? "action"
        : muted
          ? "muted"
          : skeleton
            ? "skeleton"
            : "main";

  const emphasisKey = emphasized ? "emphasized" : "normal";

  const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      (e.currentTarget as HTMLDivElement).click();
    } else if (e.key === " ") {
      e.preventDefault();
    }
    props.onKeyDown?.(e);
  };

  const handleKeyUp = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === " ") {
      e.preventDefault();
      (e.currentTarget as HTMLDivElement).click();
    }
    props.onKeyUp?.(e);
  };

  const content = (
    <div
      ref={ref}
      role="button"
      tabIndex={0}
      className={cn(
        "flex flex-row w-full items-start p-2 rounded-08 group/LineItem gap-2",
        !!(children && description) ? "items-start" : "items-center",
        buttonClassNames[variant][emphasisKey]
      )}
      data-selected={selected}
      {...props}
      onKeyDown={handleKeyDown}
      onKeyUp={handleKeyUp}
    >
      {Icon && (
        <div
          className={cn(
            "flex flex-col justify-center items-center h-[1rem] min-w-[1rem]",
            !!(children && description) && "mt-0.5"
          )}
        >
          <Icon className={cn("h-[1rem] w-[1rem]", iconClassNames[variant])} />
        </div>
      )}
      <Section alignItems="start" gap={0}>
        {children ? (
          <>
            <Section flexDirection="row" gap={0.5}>
              <Truncated
                mainUiMuted
                className={cn("text-left w-full", textClassNames[variant])}
              >
                {children}
              </Truncated>
              {rightChildren && (
                <Section alignItems="end" width="fit">
                  {rightChildren}
                </Section>
              )}
            </Section>
            {description && (
              <Truncated secondaryBody text03 className="text-left w-full">
                {description}
              </Truncated>
            )}
          </>
        ) : description ? (
          <Section flexDirection="row" gap={0.5}>
            <Truncated secondaryBody text03 className="text-left w-full">
              {description}
            </Truncated>
            {rightChildren && (
              <Section alignItems="end" width="fit">
                {rightChildren}
              </Section>
            )}
          </Section>
        ) : null}
      </Section>
    </div>
  );

  if (!href) return content;
  return <Link href={href as Route}>{content}</Link>;
}
