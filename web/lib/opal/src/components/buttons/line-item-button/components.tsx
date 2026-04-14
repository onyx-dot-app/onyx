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
import { Tooltip } from "@opal/components/tooltip/components";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ContentPassthroughProps = DistributiveOmit<
  ContentActionProps,
  "paddingVariant" | "widthVariant" | "ref"
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
  roundingVariant?: InteractiveContainerRoundingVariant;

  /** Container width. @default "full" */
  width?: ExtremaSizeVariants;

  /** Tooltip text shown on hover. */
  tooltip?: string;

  /** Which side the tooltip appears on. @default "top" */
  side?: TooltipSide;
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
  roundingVariant = "md",
  width = "full",
  tooltip,
  side = "top",

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
          paddingVariant="fit"
        />
      </Interactive.Container>
    </Interactive.Stateful>
  );

  return (
    <Tooltip tooltip={tooltip} side={side}>
      {item}
    </Tooltip>
  );
}

export { LineItemButton, type LineItemButtonProps };
