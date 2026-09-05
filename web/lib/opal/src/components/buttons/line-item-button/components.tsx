import type React from "react";
import { Interactive, type InteractiveStatefulProps } from "@opal/core";
import type {
  ExtremaSizeVariants,
  IconFunctionComponent,
  ColorTypes,
  RichStr,
  Rounding,
} from "@opal/types";
import { Tooltip, type TooltipSide } from "@opal/components";
import {
  type ContentActionProps,
  type ContentVariant,
  type SizePreset,
  ContentAction,
} from "@opal/layouts";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * The `ContentAction` props a row actually uses — nine of the twenty-two it
 * offers. Listed rather than spread, so that everything a caller passes which
 * is *not* here is DOM, and reaches the row element.
 *
 * That inversion is the point. Spreading the remainder into `ContentAction`
 * put every unrecognised prop somewhere that never renders it, so a label or a
 * handler was accepted and silently dropped. Now the leftover lands on the row
 * instead, and the compiler has the last word on the rest.
 *
 * `sizePreset` and `variant` come from the flattened aliases, which loses the
 * cross-constraint `ContentProps` keeps between them. Every call site states
 * both explicitly, so what is given up is the compiler rejecting a pair that
 * no one writes.
 */
type RowContentProps = {
  /** Main label. */
  title: string | RichStr;

  /** Leading icon. */
  icon?: IconFunctionComponent;

  /** Secondary line under the title. */
  description?: string | RichStr;

  /** Content after the label — an action button, a count, a chevron. */
  rightChildren?: React.ReactNode;

  /** Content size preset. @default "headline" */
  sizePreset?: SizePreset;

  /** Content layout variant. @default "heading" */
  variant?: ContentVariant;

  /**
   * Content colour mode. `"interactive"` is what lets the row's hover,
   * selected and disabled colours reach its title and icon; anything else
   * opts out of that.
   *
   * @default "interactive"
   */
  color?: ColorTypes;

  /** Strike the label through, e.g. a row switched off. */
  strikethrough?: boolean;

  /**
   * Padding around the inner `ContentAction`, on top of the row's own inset.
   * Narrowed to the four `Interactive.Container` applies at its size presets,
   * which is what lines a label up with an adjacent button.
   *
   * @default 0.5
   */
  padding?: 0 | 0.5 | 1 | 2;
};

type LineItemButtonOwnProps = Pick<
  InteractiveStatefulProps,
  | "state"
  | "interaction"
  | "onClick"
  | "href"
  | "target"
  | "group"
  | "ref"
  | "disabled"
> & {
  /** Interactive select variant. @default "select-light" */
  selectVariant?: "select-light" | "select-heavy";

  /** Corner rounding step (height is always content-driven). @default 3 */
  rounding?: Rounding;

  /** Container width. @default "full" */
  width?: ExtremaSizeVariants;

  /** Tooltip text shown on hover. */
  tooltip?: string;

  /** Which side the tooltip appears on. @default "top" */
  tooltipSide?: TooltipSide;
};

/**
 * `title` and `color` are omitted from the DOM attributes because the row
 * already means something by them — its label and its colour mode — and the
 * native attributes would put two meanings in one prop. `children` is omitted
 * because a row renders none: its content comes from `title` and friends.
 */
type LineItemButtonProps = LineItemButtonOwnProps &
  RowContentProps &
  Omit<React.HTMLAttributes<HTMLDivElement>, "title" | "color" | "children">;

// ---------------------------------------------------------------------------
// LineItemButton
// ---------------------------------------------------------------------------

// Mirrors native <button> activation (Enter fires on keydown, Space on keyup).
// Guarded so keystrokes on nested interactive children (e.g. `rightChildren`
// action buttons) don't also activate the row.
function handleRowKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
  if (e.target !== e.currentTarget) return;
  if (e.key === "Enter") {
    e.preventDefault();
    e.currentTarget.click();
  } else if (e.key === " ") {
    e.preventDefault();
  }
}

function handleRowKeyUp(e: React.KeyboardEvent<HTMLDivElement>) {
  if (e.target !== e.currentTarget) return;
  if (e.key === " ") {
    e.preventDefault();
    e.currentTarget.click();
  }
}

// Ignore clicks originating from nested interactive children (e.g.
// `rightChildren` action buttons) so they don't also activate the row.
function guardNestedInteractiveClick(
  onClick: React.MouseEventHandler<HTMLElement> | undefined
): React.MouseEventHandler<HTMLElement> | undefined {
  if (!onClick) return undefined;
  return (e) => {
    const nested = (e.target as HTMLElement).closest(
      'button, a, [role="button"]'
    );
    if (nested && nested !== e.currentTarget) return;
    onClick(e);
  };
}

function LineItemButton({
  // Interactive surface
  selectVariant = "select-light",
  state,
  interaction,
  onClick,
  href,
  target,
  group,
  ref,
  disabled,

  // Sizing
  rounding = 3,
  width = "full",
  tooltip,
  tooltipSide = "top",

  // Content
  title,
  icon,
  description,
  rightChildren,
  sizePreset,
  variant,
  strikethrough,
  padding,

  /*
   * Taken out of the pass-through and defaulted here rather than written
   * before the spread. A spread copies a key even when its value is
   * `undefined`, so `color={condition ? "muted" : undefined}` — the obvious
   * way to colour a row conditionally — used to overwrite the default and drop
   * the row to `"default"`, which pins its colours and stops it responding to
   * hover, selection or disablement. A destructuring default treats `undefined`
   * as absent, so that call now means what it looks like.
   */
  color = "interactive",

  /*
   * Whatever is left is DOM — labels, handlers, `data-*` — and belongs on the
   * row. It used to go the other way, into `ContentAction`, which never
   * spreads onto an element, so an unrecognised prop was accepted and then
   * silently dropped.
   */
  ...rowProps
}: LineItemButtonProps) {
  // The row renders as a focusable div (role="button") instead of a native
  // <button> so interactive `rightChildren` (e.g. action buttons) don't nest
  // a <button> inside a <button> — invalid HTML that breaks hydration.
  const rowButtonProps = href
    ? undefined
    : ({
        role: "button",
        tabIndex: 0,
        onKeyDown: handleRowKeyDown,
        onKeyUp: handleRowKeyUp,
      } as const);

  const item = (
    <Interactive.Stateful
      variant={selectVariant}
      state={state}
      interaction={interaction}
      onClick={guardNestedInteractiveClick(onClick)}
      href={href}
      target={target}
      group={group}
      ref={ref}
      disabled={disabled}
    >
      <Interactive.Container
        width={width}
        size="fit"
        rounding={rounding}
        {...rowProps}
        {...rowButtonProps}
      >
        <div className="w-full p-1.5">
          <ContentAction
            {...({
              title,
              icon,
              description,
              rightChildren,
              sizePreset,
              variant,
              strikethrough,
              color,
              padding: padding ?? 0.5,
              /*
               * `ContentActionProps` is a union whose arms pair a `sizePreset`
               * with the `variant`s valid for it. Flattening the two into
               * `SizePreset` and `ContentVariant` is what keeps a row's props
               * flat for its callers, and it costs that pairing — so the
               * assertion is the flattening, stated once, over a set this
               * component names in full. It is not the old blanket cast over
               * whatever a caller happened to pass.
               */
            } as ContentActionProps)}
          />
        </div>
      </Interactive.Container>
    </Interactive.Stateful>
  );

  return (
    <Tooltip tooltip={tooltip} side={tooltipSide}>
      {item}
    </Tooltip>
  );
}

export { LineItemButton, type LineItemButtonProps };
