import { Interactive, type InteractiveStatelessProps } from "@opal/core";
import type {
  ContainerSizeVariants,
  ExtremaSizeVariants,
  RichStr,
} from "@opal/types";
import { Text, type TooltipSide, Tooltip } from "@opal/components";
import type { IconFunctionComponent } from "@opal/types";
import { iconWrapper } from "@opal/components/buttons/icon-wrapper";
import { resolveTriggerInteraction } from "@opal/components/buttons/trigger-interaction";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ButtonContentProps =
  | {
      icon?: IconFunctionComponent;
      children: string | RichStr;
      rightIcon?: IconFunctionComponent;
      responsiveHideText?: never;
    }
  | {
      icon: IconFunctionComponent;
      children?: string | RichStr;
      rightIcon?: IconFunctionComponent;
      responsiveHideText?: boolean;
    };

type ButtonProps = InteractiveStatelessProps &
  ButtonContentProps & {
    /**
     * Size preset — controls gap, text size, and Container height/rounding.
     */
    size?: ContainerSizeVariants;

    /** Tooltip text shown on hover. */
    tooltip?: string;

    /** Width preset. `"fit"` shrink-wraps, `"full"` stretches to parent width. */
    width?: ExtremaSizeVariants;

    /** Which side the tooltip appears on. */
    tooltipSide?: TooltipSide;

    /** Applies disabled styling and suppresses clicks. */
    disabled?: boolean;
  };

// ---------------------------------------------------------------------------
// Button
// ---------------------------------------------------------------------------

function Button({
  icon: Icon,
  children,
  rightIcon: RightIcon,
  size = "lg",
  type = "button",
  width,
  tooltip,
  tooltipSide = "top",
  responsiveHideText = false,
  disabled,
  interaction,
  ...interactiveProps
}: ButtonProps) {
  const isLarge = size === "lg";
  // Only a popup trigger takes the open look: Popover, Dropdown and Dialog
  // triggers set `aria-haspopup`, a Collapsible or disclosure toggle sets
  // `data-state` but opens no popup. An open secondary trigger keeps its rest
  // fill; the stateless styles give it an outline instead of the hover look.
  const popup = interactiveProps["aria-haspopup"];
  const isPopupTrigger =
    popup !== undefined && popup !== false && popup !== "false";
  const resolvedInteraction =
    isPopupTrigger && interactiveProps.prominence !== "secondary"
      ? resolveTriggerInteraction(interaction, interactiveProps)
      : interaction;

  const labelEl = children ? (
    responsiveHideText ? (
      <span className="hidden md:inline whitespace-nowrap">
        <Text
          font={isLarge ? "main-ui-body" : "secondary-body"}
          color="inherit"
        >
          {children}
        </Text>
      </span>
    ) : (
      <Text
        font={isLarge ? "main-ui-body" : "secondary-body"}
        color="inherit"
        wordWrap="whitespace-nowrap"
      >
        {children}
      </Text>
    )
  ) : null;

  const button = (
    <Interactive.Stateless
      type={type}
      disabled={disabled}
      interaction={resolvedInteraction}
      {...interactiveProps}
    >
      <Interactive.Container
        type={type}
        border={interactiveProps.prominence === "secondary"}
        size={size}
        width={width}
        rounding={isLarge ? 3 : size === "2xs" ? 1 : 2}
      >
        <div className="flex flex-row items-center gap-1">
          {iconWrapper(Icon, size, !!children)}

          {labelEl}
          {responsiveHideText ? (
            <span className="hidden md:inline-flex">
              {iconWrapper(RightIcon, size, !!children)}
            </span>
          ) : (
            iconWrapper(RightIcon, size, !!children)
          )}
        </div>
      </Interactive.Container>
    </Interactive.Stateless>
  );

  return (
    <Tooltip tooltip={tooltip} side={tooltipSide}>
      {button}
    </Tooltip>
  );
}

export { Button, type ButtonProps };
