import "@opal/components/buttons/Button/styles.css";
import { Interactive, type InteractiveBaseVariantProps } from "@opal/core";
import type { IconFunctionComponent } from "@opal/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ButtonProps = InteractiveBaseVariantProps & {
  /** Left icon component (renders at 1rem x 1rem). */
  icon?: IconFunctionComponent;

  /** Button label text. Omit for icon-only buttons. */
  children?: string;

  /** Right icon component (renders at 1rem x 1rem). */
  rightIcon?: IconFunctionComponent;

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

export { Button, type ButtonProps };
