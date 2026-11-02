"use client";

import "@opal/components/buttons/sidebar-tab/styles.css";
import React from "react";
import type { ButtonType, IconFunctionComponent, RichStr } from "@opal/types";
import type { Route } from "next";
import { Interactive, type InteractiveStatefulVariant } from "@opal/core";
import { useSidebarFolded } from "@opal/layouts/sidebar/context";
import { Text, Tooltip } from "@opal/components";
import useOverflow from "@opal/hooks/useOverflow";
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
   * Set it only to override that — outside a sidebar, or in a skeleton.
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

  /** Tooltip shown on hover. Takes precedence over the label tooltip. */
  tooltip?: string | RichStr;
}

// ---------------------------------------------------------------------------
// LabelTooltip
// ---------------------------------------------------------------------------

interface LabelTooltipProps {
  /** The tab's label, shown in full. */
  label: string | RichStr;

  /** Explicit fold state. Falls back to the enclosing sidebar's. */
  folded?: boolean;

  /** The rendered title, measured to tell whether the tab cuts it off. */
  titleElement: HTMLElement | null;

  children: React.ReactElement;
}

/**
 * Shows the full `label` on hover while the tab is folded, or while the
 * unfolded tab cuts the title off with an ellipsis. Its trigger is the
 * overlay that covers the whole tab, so the tab is the anchor, not the text.
 *
 * The fold state and the title's overflow are the parts CSS cannot express,
 * so they are split out: this component subscribes to them, and the tab does
 * not. On a fold, or when the title starts or stops overflowing, React
 * re-renders this wrapper alone — `children` is the same element it received
 * before, so nothing below it re-renders.
 *
 * The tooltip stays mounted and is suppressed instead of being added and
 * removed. Dropping it would change the tree shape, which remounts the
 * trigger.
 */
function LabelTooltip({
  label,
  folded,
  titleElement,
  children,
}: LabelTooltipProps) {
  const foldedFromSidebar = useSidebarFolded();
  const overflowing = useOverflow(titleElement);

  const effectiveFolded = folded ?? foldedFromSidebar;

  /* `suppressed`, not a controlled `open`: hover stays Radix's to track, so the
  tab keeps no hover state of its own that a later fold could act on. */
  return (
    <Tooltip
      tooltip={label}
      side="end"
      suppressed={!effectiveFolded && !overflowing}
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
 * for color styling. The click target is an overlay control — a `Link` when
 * `href` is set, a `button` when only `onClick` is set — so both paths are
 * keyboard focusable. Supports `rightChildren` for inline actions, and folded
 * mode. A string label shows in a tooltip while folded or cut off.
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

  // The label and `rightChildren` sit in one fold wrapper, so they fade
  // together. `rightChildren` stays absolutely positioned against the tab.
  const actions = rightChildren && (
    <div className="opal-sidebar-tab__actions">{rightChildren}</div>
  );

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
  const [titleElement, setTitleElement] = React.useState<HTMLElement | null>(
    null
  );
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
      <Tooltip tooltip={tooltip} side="end">
        {overlay}
      </Tooltip>
    ) : label !== undefined ? (
      // Only a string label can stand in as its own tooltip.
      <LabelTooltip label={label} folded={folded} titleElement={titleElement}>
        {overlay}
      </LabelTooltip>
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
        <Interactive.Container rounding={2} size="lg" width="full">
          {trigger}

          {label !== undefined ? (
            <div className="opal-sidebar-tab__row">
              <div className="opal-sidebar-tab__content">
                {Icon && (
                  <div className="opal-sidebar-tab__icon">
                    <Icon className="opal-sidebar-tab__icon-svg" />
                  </div>
                )}
                <div className="opal-sidebar-tab__fold">
                  <Text
                    font="main-ui-body"
                    color="inherit"
                    maxLines={1}
                    ref={setTitleElement}
                  >
                    {label}
                  </Text>
                  {actions}
                </div>
              </div>
              {truncationSpacer && (
                <div className="opal-sidebar-tab__spacer">
                  {truncationSpacer}
                </div>
              )}
            </div>
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
              <div className="opal-sidebar-tab__fold" data-label="element">
                {children}
                {actions}
              </div>
              {truncationSpacer}
            </div>
          )}
        </Interactive.Container>
      </Interactive.Stateful>
    </div>
  );
}

export { SidebarTab, type SidebarTabProps };
