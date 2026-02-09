import { Interactive, type InteractiveBaseVariantProps } from "@opal/core";
import type { IconProps } from "@opal/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type IconComponent = React.ComponentType<IconProps>;

export type ButtonProps = InteractiveBaseVariantProps & {
  /** Left icon component (renders at 1rem x 1rem). */
  icon?: IconComponent;

  /** Button label text. Omit for icon-only buttons. */
  children?: string;

  /** Right icon component (renders at 1rem x 1rem). */
  rightIcon?: IconComponent;

  /** Size preset — controls gap, text size, and Container height/rounding. */
  size?: "default" | "compact";

  /** When `true`, forces the selected visual state. */
  selected?: boolean;

  /** When `true`, disables the button. */
  disabled?: boolean;

  /** URL to navigate to when clicked (renders an `<a>` internally). */
  href?: string;

  /** Click handler. */
  onClick?: React.MouseEventHandler<HTMLElement>;
};

// ---------------------------------------------------------------------------
// Button
// ---------------------------------------------------------------------------

function Button({
  icon: Icon,
  children,
  rightIcon: RightIcon,
  size = "default",
  variant,
  subvariant,
  ...baseProps
}: ButtonProps) {
  const isCompact = size === "compact";

  return (
    <Interactive.Base
      {...({ variant, subvariant } as InteractiveBaseVariantProps)}
      {...baseProps}
    >
      <Interactive.Container
        heightVariant={isCompact ? "compact" : "default"}
        roundingVariant={isCompact ? "compact" : "default"}
        paddingVariant={isCompact ? "thin" : "default"}
      >
        <div
          className="opal-button interactive-foreground"
          data-size={isCompact ? "compact" : undefined}
        >
          {Icon && <Icon className="opal-button-icon" />}
          {children && <span className="opal-button-label">{children}</span>}
          {RightIcon && <RightIcon className="opal-button-icon" />}
        </div>
      </Interactive.Container>
    </Interactive.Base>
  );
}

export { Button };
