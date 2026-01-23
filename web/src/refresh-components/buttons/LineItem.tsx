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

export interface LineItemProps
  extends Omit<
    WithoutStyles<React.HTMLAttributes<HTMLButtonElement>>,
    "children"
  > {
  // line-item variants
  strikethrough?: boolean;
  danger?: boolean;

  // modifier (makes the background more pronounced when selected).
  emphasized?: boolean;

  selected?: boolean;
  icon?: React.FunctionComponent<IconProps>;
  description?: string;
  rightChildren?: React.ReactNode;
  href?: string;
  ref?: React.Ref<HTMLButtonElement>;
  children: string;
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
 * ```
 *
 * @remarks
 * - Variants are mutually exclusive: only one of `strikethrough` or `danger` should be used
 * - The `selected` prop modifies text/icon colors for `main` and `danger` variants
 * - The `emphasized` prop adds background colors when combined with `selected`
 * - The component automatically adds a `data-selected="true"` attribute for custom styling
 */
export default function LineItem({
  selected,
  strikethrough,
  danger,
  emphasized,
  icon: Icon,
  description,
  children,
  rightChildren,
  href,
  ref,
  ...props
}: LineItemProps) {
  // Determine variant (mutually exclusive, with priority order)
  const variant = strikethrough ? "strikethrough" : danger ? "danger" : "main";

  const emphasisKey = emphasized ? "emphasized" : "normal";

  const content = (
    <button
      ref={ref}
      className={cn(
        "flex flex-row w-full items-start p-2 rounded-08 group/LineItem gap-2",
        !!description ? "items-start" : "items-center",
        buttonClassNames[variant][emphasisKey]
      )}
      type="button"
      data-selected={selected}
      {...props}
    >
      {Icon && (
        <div
          className={cn(
            "flex flex-col justify-center items-center h-[1rem] min-w-[1rem]",
            !!description && "mt-0.5"
          )}
        >
          <Icon className={cn("h-[1rem] w-[1rem]", iconClassNames[variant])} />
        </div>
      )}
      <Section alignItems="start" gap={0}>
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
      </Section>
    </button>
  );

  if (!href) return content;
  return <Link href={href as Route}>{content}</Link>;
}
