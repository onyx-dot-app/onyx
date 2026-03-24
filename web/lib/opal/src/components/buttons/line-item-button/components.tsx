import {
  Interactive,
  type InteractiveStatefulProps,
  InteractiveContainerRoundingVariant,
} from "@opal/core";
import type { ExtremaSizeVariants } from "@opal/types";
import type { TooltipSide } from "@opal/components";
import type { DistributiveOmit } from "@opal/types";
import type { ContentActionProps } from "@opal/layouts/content-action/components";
import { ContentAction } from "@opal/layouts";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ContentPassthroughProps = DistributiveOmit<
  ContentActionProps,
  "paddingVariant" | "widthVariant" | "ref" | "withInteractive"
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

  /** Corner rounding preset (height is always content-driven). @default "default" */
  roundingVariant?: InteractiveContainerRoundingVariant;

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
  roundingVariant = "default",
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
        widthVariant={width}
        heightVariant="lg"
        roundingVariant={roundingVariant}
      >
        <ContentAction
          {...(contentActionProps as ContentActionProps)}
          withInteractive
          paddingVariant="fit"
        />
      </Interactive.Container>
    </Interactive.Stateful>
  );

  if (!tooltip) return item;

  return (
    <TooltipPrimitive.Root>
      <TooltipPrimitive.Trigger asChild>{item}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          className="opal-tooltip"
          side={tooltipSide}
          sideOffset={4}
        >
          {tooltip}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}

export { LineItemButton, type LineItemButtonProps };
