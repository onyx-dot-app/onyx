"use client";

import React from "react";
import type { ButtonType, IconFunctionComponent } from "@opal/types";
import type { Route } from "next";
import { Interactive, type InteractiveStatefulVariant } from "@opal/core";
import { ContentAction } from "@opal/layouts";
import { Text, Tooltip } from "@opal/components";
import Link from "next/link";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SidebarTabProps {
  /** Collapses the label, showing only the icon. */
  folded?: boolean;

  /** Marks this tab as the currently active/selected item. */
  selected?: boolean;

  /**
   * Sidebar color variant.
   * @default "sidebar-heavy"
   */
  variant?: Extract<
    InteractiveStatefulVariant,
    "sidebar-light" | "sidebar-heavy"
  >;

  /** Renders an empty spacer in place of the icon for nested items. */
  nested?: boolean;

  /** Disables the tab — applies muted colors and suppresses clicks. */
  disabled?: boolean;

  onClick?: React.MouseEventHandler<HTMLElement>;
  href?: string;
  type?: ButtonType;
  icon?: IconFunctionComponent;
  children?: React.ReactNode;

  /** Content rendered on the right side (e.g. action buttons). */
  rightChildren?: React.ReactNode;
}

// ---------------------------------------------------------------------------
// SidebarTab
// ---------------------------------------------------------------------------

/**
 * Sidebar navigation tab built on `Interactive.Stateful` > `Interactive.Container`.
 *
 * Uses `sidebar-heavy` (default) or `sidebar-light` (via `variant`) variants
 * for color styling. Supports an overlay `Link` for client-side navigation,
 * `rightChildren` for inline actions, and folded mode with an auto-tooltip.
 */
function SidebarTab({
  folded,
  selected,
  variant = "sidebar-heavy",
  nested,
  disabled,

  onClick,
  href,
  type,
  icon,
  rightChildren,
  children,
}: SidebarTabProps) {
  const Icon =
    icon ??
    (nested
      ? ((() => (
          <div className="w-6" aria-hidden="true" />
        )) as IconFunctionComponent)
      : null);

  // The `rightChildren` node is absolutely positioned to sit on top of the
  // overlay Link. A zero-width spacer reserves truncation space for the title.
  const truncationSpacer = rightChildren && (
    <div className="w-0 group-hover/SidebarTab:w-6" />
  );

  const content = (
    <div className="relative">
      <Interactive.Stateful
        variant={variant}
        state={selected ? "selected" : "empty"}
        disabled={disabled}
        onClick={onClick}
        type="button"
        group="group/SidebarTab"
      >
        <Interactive.Container rounding="sm" size="lg" width="full" type={type}>
          {href && !disabled && (
            <Link
              href={href as Route}
              scroll={false}
              className="absolute z-[99] inset-0 rounded-08"
              tabIndex={-1}
            />
          )}

          {!folded && rightChildren && (
            <div className="absolute z-[100] right-1.5 top-0 bottom-0 flex flex-col justify-center items-center pointer-events-auto">
              {rightChildren}
            </div>
          )}

          {typeof children === "string" ? (
            <ContentAction
              icon={Icon ?? undefined}
              title={folded ? "" : children}
              sizePreset="main-ui"
              variant="body"
              color="interactive"
              width="full"
              padding="fit"
              rightChildren={truncationSpacer}
            />
          ) : (
            <div className="flex flex-row items-center gap-2 w-full">
              {Icon && (
                <div className="flex items-center justify-center p-0.5">
                  <Icon className="h-[1rem] w-[1rem] text-text-03" />
                </div>
              )}
              {children}
              {truncationSpacer}
            </div>
          )}
        </Interactive.Container>
      </Interactive.Stateful>
    </div>
  );

  if (typeof children !== "string") return content;
  if (folded) {
    return (
      <Tooltip tooltip={children} side="right">
        {content}
      </Tooltip>
    );
  }
  return content;
}

export { SidebarTab, type SidebarTabProps };
