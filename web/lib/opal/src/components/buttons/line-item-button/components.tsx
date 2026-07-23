import type React from "react";
import {
  Interactive,
  type InteractiveStatefulProps,
  InteractiveContainerRoundingVariant,
} from "@opal/core";
import type { ExtremaSizeVariants, DistributiveOmit } from "@opal/types";
import { Tooltip, type TooltipSide } from "@opal/components";
import { type ContentActionProps, ContentAction } from "@opal/layouts";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ContentPassthroughProps = DistributiveOmit<
  ContentActionProps,
  "padding" | "width" | "ref"
>;

type LineItemButtonOwnProps = Pick<
  InteractiveStatefulProps,
  "state" | "interaction" | "onClick" | "href" | "target" | "group" | "ref"
> & {
  /** Interactive select variant. @default "select-light" */
  selectVariant?: "select-light" | "select-heavy";

  /** Corner rounding preset (height is always content-driven). @default "md" */
  rounding?: InteractiveContainerRoundingVariant;

  /** Container width. @default "full" */
  width?: ExtremaSizeVariants;

  /** Tooltip text shown on hover. */
  tooltip?: string;

  /** Which side the tooltip appears on. @default "top" */
  tooltipSide?: TooltipSide;
};

type LineItemButtonProps = ContentPassthroughProps & LineItemButtonOwnProps;

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

  // Sizing
  rounding = "md",
  width = "full",
  tooltip,
  tooltipSide = "top",

  // ContentAction pass-through
  ...contentActionProps
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
    >
      <Interactive.Container
        width={width}
        size="fit"
        rounding={rounding}
        {...rowButtonProps}
      >
        <div className="w-full p-2">
          <ContentAction
            color="interactive"
            {...(contentActionProps as ContentActionProps)}
            padding="fit"
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
