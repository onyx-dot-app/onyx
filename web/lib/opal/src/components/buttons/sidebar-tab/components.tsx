"use client";

import "@opal/components/buttons/sidebar-tab/styles.css";
import React from "react";
import type { ButtonType, IconFunctionComponent, RichStr } from "@opal/types";
import type { Route } from "next";
import { Interactive, type InteractiveStatefulVariant } from "@opal/core";
import { ContentAction } from "@opal/layouts";
import { useSidebarFolded } from "@opal/layouts/sidebar/context";
import { Tooltip } from "@opal/components";
import Link from "next/link";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SidebarTabProps {
  /**
   * Collapses the label, showing only the icon.
   *
   * Leave this unset inside a sidebar: the enclosing `SidebarRoot` publishes
   * its fold state as a `data-folded` attribute, and CSS collapses the label.
   * Set it only to override that — outside a sidebar, in Storybook, or in a
   * skeleton.
   */
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

  /** Tooltip shown on hover. Takes precedence over the folded-name tooltip. */
  tooltip?: string | RichStr;
}

// ---------------------------------------------------------------------------
// FoldedTooltip
// ---------------------------------------------------------------------------

interface FoldedTooltipProps {
  /** Label to show while the tab is folded. */
  label: string | RichStr;

  /** Explicit fold state. Falls back to the enclosing sidebar's. */
  folded?: boolean;

  children: React.ReactElement;
}

/**
 * Shows `label` on hover, but only while the tab is folded.
 *
 * This is the one part of the folded look that CSS cannot express, so it is
 * split out: this component subscribes to the fold state, and the tab does
 * not. On a fold toggle React re-renders this wrapper alone — `children` is
 * the same element it received before, so the tab below it never re-renders.
 *
 * The tooltip stays mounted and is gated by `open` instead of being added and
 * removed. Changing the tree shape on a fold would remount the tab and cut the
 * label's fade short.
 */
function FoldedTooltip({ label, folded, children }: FoldedTooltipProps) {
  const foldedFromSidebar = useSidebarFolded();
  const [hovered, setHovered] = React.useState(false);

  const effectiveFolded = folded ?? foldedFromSidebar;

  return (
    <Tooltip
      tooltip={label}
      side="right"
      open={effectiveFolded && hovered}
      onOpenChange={setHovered}
    >
      {children}
    </Tooltip>
  );
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
 *
 * The label and `rightChildren` always render. The folded state hides them in
 * CSS — see `styles.css` — so folding a sidebar re-renders no tabs.
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
  tooltip,
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

  // A folded tab hides its label, and neither the overlay Link nor the button
  // holds text of its own, so name them explicitly. Without this a folded tab
  // is an unnamed control.
  const label = typeof children === "string" ? children : undefined;

  const content = (
    <div
      className="opal-sidebar-tab"
      data-folded={folded === undefined ? undefined : String(folded)}
    >
      <Interactive.Stateful
        variant={variant}
        state={selected ? "selected" : "empty"}
        disabled={disabled}
        onClick={onClick}
        type="button"
        group="group/SidebarTab"
      >
        <Interactive.Container
          rounding="sm"
          size="lg"
          width="full"
          type={type}
          // Only when `type` makes this a real button — `aria-label` on a
          // plain div names nothing.
          aria-label={type ? label : undefined}
        >
          {href && !disabled && (
            <Link
              href={href as Route}
              scroll={false}
              className="absolute z-99 inset-0 rounded-08"
              tabIndex={-1}
              aria-label={label}
            />
          )}

          {rightChildren && (
            <div className="opal-sidebar-tab__actions">{rightChildren}</div>
          )}

          {typeof children === "string" ? (
            <ContentAction
              icon={Icon ?? undefined}
              title={children}
              sizePreset="main-ui"
              variant="body"
              color="interactive"
              width="full"
              padding="fit"
              rightChildren={truncationSpacer}
              titleMaxLines={1}
            />
          ) : (
            <div className="flex flex-row items-center gap-2 w-full">
              {Icon && (
                <div className="flex items-center justify-center p-0.5">
                  <Icon className="h-4 w-4 text-text-03" />
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

  if (tooltip) {
    return (
      <Tooltip tooltip={tooltip} side="right">
        {content}
      </Tooltip>
    );
  }

  // Only a string label can stand in as its own tooltip.
  if (label === undefined) return content;

  return (
    <FoldedTooltip label={label} folded={folded}>
      {content}
    </FoldedTooltip>
  );
}

export { SidebarTab, type SidebarTabProps };
