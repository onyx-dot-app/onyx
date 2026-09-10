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
 * The `ContentAction` props a row actually uses — eleven of the twenty-two it
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

  /**
   * Cap the title at N lines and truncate the rest. Unset wraps without a
   * limit, so a row showing a user-authored name usually wants `1`.
   */
  titleMaxLines?: number;

  /** Leading icon. */
  icon?: IconFunctionComponent;

  /** Secondary line under the title. */
  description?: string | RichStr;

  /**
   * Cap the description at N lines and truncate the rest. Unset wraps without
   * a limit, so a row showing user-authored text usually wants `1`.
   */
  descriptionMaxLines?: number;

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

/**
 * `presentational` and `href` are mutually exclusive. An anchor is a native
 * control — focusable, activated by Enter — which is exactly what the
 * presentational mode promises the row will not be.
 */
type LineItemButtonModeProps =
  | {
      /**
       * Render the row as plain markup inside another interactive primitive
       * (e.g. Radix Select.Item, a selectable table row): no button role, no
       * tab stop, no Enter/Space activation. The row keeps its interactive
       * palette — drive it with `state` / `selectVariant` / `interaction`
       * from the owning control. `role`, `tabIndex` and the key handlers
       * still pass through, so the owner can substitute its own semantics.
       */
      presentational: true;
      href?: never;
      target?: never;
    }
  | ({ presentational?: false } & Pick<
      InteractiveStatefulProps,
      "href" | "target"
    >);

type LineItemButtonOwnProps = Pick<
  InteractiveStatefulProps,
  "state" | "interaction" | "onClick" | "group" | "ref" | "disabled"
> &
  LineItemButtonModeProps & {
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

// The caller's handler runs first and can stop the row's own activation with
// `preventDefault()` — the order a native control gives you. Composed rather
// than replaced, because a row that accepts a handler and then overwrites it
// is the same silent drop this component exists to avoid.
function composeKeyHandler(
  caller: React.KeyboardEventHandler<HTMLDivElement> | undefined,
  row: React.KeyboardEventHandler<HTMLDivElement>
): React.KeyboardEventHandler<HTMLDivElement> {
  if (!caller) return row;
  return (e) => {
    caller(e);
    if (!e.defaultPrevented) row(e);
  };
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
  presentational,

  // Content
  title,
  titleMaxLines,
  icon,
  description,
  descriptionMaxLines,
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
   * Named so the row can defer to a caller's value instead of overwriting it.
   * They would otherwise ride `rowProps` onto the container and be replaced by
   * the button semantics spread after it — accepted by the type, then gone.
   */
  role,
  tabIndex,
  onKeyDown,
  onKeyUp,

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
  // a <button> inside a <button> — invalid HTML that breaks hydration. An
  // anchor row is already focusable and already activates on Enter, so it
  // takes the caller's values unchanged. A presentational row makes no
  // control of its own — the primitive that owns it already carries the
  // semantics and the keyboard handling — so the caller's values pass
  // through untouched there too.
  const rowButtonProps: Pick<
    React.HTMLAttributes<HTMLDivElement>,
    "role" | "tabIndex" | "onKeyDown" | "onKeyUp"
  > = presentational
    ? { role: role ?? "presentation", tabIndex, onKeyDown, onKeyUp }
    : href
      ? { role, tabIndex, onKeyDown, onKeyUp }
      : {
          role: role ?? "button",
          tabIndex: tabIndex ?? 0,
          onKeyDown: composeKeyHandler(onKeyDown, handleRowKeyDown),
          onKeyUp: composeKeyHandler(onKeyUp, handleRowKeyUp),
        };

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
              titleMaxLines,
              icon,
              description,
              descriptionMaxLines,
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
