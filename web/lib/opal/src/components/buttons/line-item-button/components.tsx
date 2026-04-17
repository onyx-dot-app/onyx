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
  | "state"
  | "interaction"
  | "onClick"
  | "href"
  | "target"
  | "group"
  | "ref"
  | "type"
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
  type = "button",

  // Sizing
  rounding = "md",
  width = "full",
  tooltip,
  tooltipSide = "top",

  // ContentAction pass-through
  ...contentActionProps
}: LineItemButtonProps) {
  const item = (
    <Interactive.Stateful
      variant={selectVariant}
      state={state}
      interaction={interaction}
      onClick={onClick}
      href={href}
      target={target}
      group={group}
      ref={ref}
    >
      <Interactive.Container
        type={type}
        width={width}
        size="fit"
        rounding={rounding}
      >
        <div className="w-full p-2">
          <ContentAction
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
