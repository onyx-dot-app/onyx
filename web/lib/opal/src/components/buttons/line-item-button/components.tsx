import "@opal/components/tooltip.css";
import {
  Disabled,
  Interactive,
  type InteractiveStatefulProps,
} from "@opal/core";
import type { SizeVariant, WidthVariant } from "@opal/shared";
import type { TooltipSide } from "@opal/components";
import type { ContentActionProps } from "@opal/layouts/content-action/components";
import { ContentAction } from "@opal/layouts";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ContentPassthroughProps = Omit<
  ContentActionProps,
  "paddingVariant" | "widthVariant" | "ref" | "withInteractive"
>;

interface LineItemButtonProps extends ContentPassthroughProps {
  /** Interactive select variant. @default "select-light" */
  selectVariant?: "select-light" | "select-heavy";

  /** Whether this item is selected. */
  selected?: boolean;

  /** Whether this item is disabled. */
  disabled?: boolean;

  /** Click handler. */
  onClick?: InteractiveStatefulProps["onClick"];

  /** When provided, renders an anchor instead of a div. */
  href?: string;

  /** Anchor target (e.g. "_blank"). */
  target?: string;

  /** Interactive group key. */
  group?: string;

  /** Forwarded ref. */
  ref?: React.Ref<HTMLElement>;

  /** Container height. @default "lg" */
  size?: Exclude<SizeVariant, "fit">;

  /** Container width. @default "full" */
  width?: WidthVariant;

  /** HTML button type. @default "button" */
  type?: "submit" | "button" | "reset";

  /** Tooltip text shown on hover. */
  tooltip?: string;

  /** Which side the tooltip appears on. @default "top" */
  tooltipSide?: TooltipSide;
}

// ---------------------------------------------------------------------------
// LineItemButton
// ---------------------------------------------------------------------------

function LineItemButton({
  // Interactive surface
  selectVariant = "select-light",
  selected,
  disabled,
  onClick,
  href,
  target,
  group,
  ref,

  // Sizing
  size = "lg",
  width = "full",
  type = "button",
  tooltip,
  tooltipSide = "top",

  // ContentAction pass-through
  ...contentActionProps
}: LineItemButtonProps) {
  const item = (
    <Disabled disabled={disabled}>
      <Interactive.Stateful
        variant={selectVariant}
        state={selected ? "selected" : "empty"}
        onClick={onClick}
        href={href}
        target={target}
        group={group}
        ref={ref}
      >
        <Interactive.Container
          type={type}
          widthVariant={width}
          heightVariant={size}
          roundingVariant={
            size === "lg" ? "default" : size === "2xs" ? "mini" : "compact"
          }
        >
          <ContentAction
            {...(contentActionProps as ContentActionProps)}
            withInteractive
            paddingVariant="fit"
          />
        </Interactive.Container>
      </Interactive.Stateful>
    </Disabled>
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
