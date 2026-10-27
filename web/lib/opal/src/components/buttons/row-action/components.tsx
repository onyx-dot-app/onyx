import { Interactive, type InteractiveStatelessProps } from "@opal/core";
import type {
  DistributiveOmit,
  IconFunctionComponent,
  OverridableExtremaSizeVariants,
  RichStr,
} from "@opal/types";
import { Text, Tooltip, type TooltipSide } from "@opal/components";
import { Section } from "@opal/layouts/general/components";
import { iconWrapper } from "@opal/components/buttons/icon-wrapper";
import { ChevronIcon } from "@opal/components/buttons/chevron";
import { resolveTriggerInteraction } from "@opal/components/buttons/trigger-interaction";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * The right slot holds one thing: a free `rightIcon`, or the dropdown
 * `chevron`.
 */
type RowActionTrailingProps =
  | {
      /** Icon at the right edge, e.g. a transfer or open-in-new icon. */
      rightIcon?: IconFunctionComponent;
      chevron?: false;
    }
  | {
      rightIcon?: never;
      /**
       * A chevron at the right edge for a dropdown trigger. It rotates while
       * the trigger is open.
       */
      chevron: true;
    };

type RowActionProps = DistributiveOmit<
  InteractiveStatelessProps,
  "children" | "type" | "passive" | "group" | "prominence"
> &
  RowActionTrailingProps & {
    /** Icon before the title. */
    icon?: IconFunctionComponent;

    /** The title. */
    children: string | RichStr;

    /**
     * `"fit"`, `"full"`, or a fixed length as a spacing step (`N / 4` rem).
     * @default "full"
     */
    width?: OverridableExtremaSizeVariants;

    /** Tooltip text shown on hover. */
    tooltip?: string;

    /** Which side the tooltip appears on. @default "top" */
    tooltipSide?: TooltipSide;

    /** Applies disabled styling and suppresses clicks. */
    disabled?: boolean;
  };

// ---------------------------------------------------------------------------
// RowAction
// ---------------------------------------------------------------------------

/**
 * The value or action at the end of a row: icon and title on the left, a
 * `rightIcon` or `chevron` at the right edge. Every mode shares one box, so
 * a column of them lines up.
 *
 * The props decide the mode: `onClick` makes a button (a `Dropdown.Trigger`
 * passes one, so a trigger is a button too), `href` a link, and neither a
 * static row with no hover, role or tab stop.
 */
function RowAction({
  icon: Icon,
  children,
  rightIcon,
  chevron,
  width = "full",
  tooltip,
  tooltipSide = "top",
  disabled,
  interaction,
  ...interactiveProps
}: RowActionProps) {
  const isStatic = !interactiveProps.onClick && !interactiveProps.href;

  // Open popup triggers (Popover, Dropdown) keep the hover look, which also
  // turns the chevron.
  const popup = interactiveProps["aria-haspopup"];
  const isPopupTrigger =
    popup !== undefined && popup !== false && popup !== "false";
  const resolvedInteraction = isPopupTrigger
    ? resolveTriggerInteraction(interaction, interactiveProps)
    : interaction;

  const TrailingIcon = chevron ? ChevronIcon : rightIcon;

  const row = (
    <Interactive.Stateless
      type={isStatic || interactiveProps.href ? undefined : "button"}
      passive={isStatic}
      disabled={disabled}
      interaction={resolvedInteraction}
      // Always internal: transparent at rest, so the row behind it shows.
      prominence="internal"
      {...interactiveProps}
    >
      <Interactive.Container
        type={isStatic || interactiveProps.href ? undefined : "button"}
        size="lg"
        width={width}
        // 8px: concentric with a table row's 12px corners at the cell's 4px
        // inset.
        rounding={2}
      >
        <Section
          flexDirection="row"
          justifyContent="between"
          gap={1}
          height="auto"
        >
          <Section flexDirection="row" gap={1} width="fit" height="auto">
            {iconWrapper(Icon, "lg", true)}
            <Text
              font="main-ui-action"
              color="inherit"
              wordWrap="whitespace-nowrap"
            >
              {children}
            </Text>
          </Section>
          {iconWrapper(TrailingIcon, "lg", false)}
        </Section>
      </Interactive.Container>
    </Interactive.Stateless>
  );

  return (
    <Tooltip tooltip={tooltip} side={tooltipSide}>
      {row}
    </Tooltip>
  );
}

export { RowAction, type RowActionProps };
