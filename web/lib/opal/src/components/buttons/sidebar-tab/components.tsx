"use client";

import "@opal/components/buttons/sidebar-tab/styles.css";
import React from "react";
import type { ButtonType, IconFunctionComponent, RichStr } from "@opal/types";
import type { Route } from "next";
import { Interactive, type InteractiveStatefulVariant } from "@opal/core";
import { ContentAction } from "@opal/layouts";
import { useSidebarFolded } from "@opal/layouts/sidebar/context";
import { Tooltip } from "@opal/components";
import { cn } from "@opal/utils";
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

  /**
   * HTML button type for the click target. Ignored when `href` is set.
   * @default "button"
   */
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
 * the same element it received before, so nothing below it re-renders.
 *
 * The tooltip stays mounted and is suppressed while unfolded instead of being
 * added and removed. Dropping it would change the tree shape on a fold, which
 * remounts the trigger.
 */
function FoldedTooltip({ label, folded, children }: FoldedTooltipProps) {
  const foldedFromSidebar = useSidebarFolded();

  const effectiveFolded = folded ?? foldedFromSidebar;

  /* `suppressed`, not a controlled `open`: hover stays Radix's to track, so an
  unfolded tab keeps no hover state of its own that a later fold could act on. */
  return (
    <Tooltip tooltip={label} side="right" suppressed={!effectiveFolded}>
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
 * for color styling. The click target is an overlay control — a `Link` when
 * `href` is set, a `button` when only `onClick` is set — so both paths are
 * keyboard focusable. Supports `rightChildren` for inline actions, and folded
 * mode with an auto-tooltip.
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
          <div className="w-4" aria-hidden="true" />
        )) as IconFunctionComponent)
      : null);

  // The `rightChildren` node is absolutely positioned to sit on top of the
  // overlay control. A zero-width spacer reserves truncation space for the title.
  const truncationSpacer = rightChildren && (
    <div className="w-0 group-hover/SidebarTab:w-6" />
  );

  /* The overlay holds no text of its own, and a folded tab hides its label, so
  name the overlay explicitly. String children name it directly. Other content
  (truncated or animated titles) names it through the element that renders the
  title. */
  const label = typeof children === "string" ? children : undefined;
  const labelId = React.useId();
  const labelProps =
    label !== undefined
      ? { "aria-label": label }
      : { "aria-labelledby": labelId };

  /* The click target is an overlay that covers the whole row: a `Link` when
  `href` is set, a `button` otherwise. It stays a sibling of the content so that
  `rightChildren` and interactive icons remain valid nested controls. The focus
  outline is inset because the container clips its overflow. `cursor-pointer` is
  explicit because the UA stylesheet gives `button` a default cursor, which wins
  over the value inherited from `.interactive`. */
  const overlayClassName = "absolute z-99 inset-0 rounded-08";
  const controlClassName = cn(
    overlayClassName,
    "cursor-pointer outline-border-04 outline-offset-[-2px] focus-visible:outline-2"
  );
  /* The tooltip hangs off the overlay, not the tab, so the tab's tree shape
  never depends on whether there is one. Swapping `children` between a label and
  an element (an inline rename input) then re-renders the row instead of
  remounting it. A tab without a control gets an inert overlay as the trigger
  when it has a tooltip to show. */
  const overlay =
    !disabled && href ? (
      <Link
        href={href as Route}
        scroll={false}
        onClick={onClick}
        {...labelProps}
        className={controlClassName}
      />
    ) : !disabled && onClick ? (
      <button
        type={type ?? "button"}
        onClick={onClick}
        {...labelProps}
        className={controlClassName}
      />
    ) : tooltip || label !== undefined ? (
      <div aria-hidden="true" className={overlayClassName} />
    ) : null;
  const trigger =
    overlay &&
    (tooltip ? (
      <Tooltip tooltip={tooltip} side="right">
        {overlay}
      </Tooltip>
    ) : label !== undefined ? (
      // Only a string label can stand in as its own folded tooltip.
      <FoldedTooltip label={label} folded={folded}>
        {overlay}
      </FoldedTooltip>
    ) : (
      overlay
    ));

  return (
    <div
      className="opal-sidebar-tab"
      data-folded={folded === undefined ? undefined : String(folded)}
    >
      <Interactive.Stateful
        variant={variant}
        state={selected ? "selected" : "empty"}
        disabled={disabled}
        type="button"
        group="group/SidebarTab"
      >
        <Interactive.Container rounding="sm" size="lg" width="full">
          {trigger}

          {rightChildren && (
            <div className="opal-sidebar-tab__actions">{rightChildren}</div>
          )}

          {label !== undefined ? (
            <ContentAction
              icon={Icon ?? undefined}
              title={label}
              sizePreset="main-ui"
              variant="body"
              color="interactive"
              width="full"
              padding={0}
              rightChildren={truncationSpacer}
              titleMaxLines={1}
            />
          ) : (
            <div
              id={labelId}
              className="flex flex-row items-center gap-2 w-full"
            >
              {Icon && (
                /* Sits above the overlay so an interactive icon stays clickable. */
                <div className="relative z-100 flex items-center justify-center p-0.5">
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
}

export { SidebarTab, type SidebarTabProps };
