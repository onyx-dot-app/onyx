import "@opal/components/buttons/OpenButton/styles.css";
import {
  Interactive,
  type InteractiveBaseVariantProps,
  type InteractiveContainerProps,
} from "@opal/core";
import { SvgChevronDownSmall } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type OpenButtonProps = InteractiveBaseVariantProps & {
  /**
   * Explicit open/expanded state for the chevron rotation.
   *
   * When `true`, the chevron rotates 180° to point upward (indicating "open").
   * When `false` or `undefined`, falls back to checking for a Radix
   * `data-state="open"` attribute (injected by components like `Popover.Trigger`).
   *
   * This dual-resolution allows the component to work automatically with Radix
   * primitives while also supporting explicit control when needed.
   *
   * @default undefined (falls back to Radix data-state)
   */
  open?: boolean;

  /** Left icon component (renders at 1rem x 1rem). */
  icon?: IconFunctionComponent;

  /** Content rendered between the icon and chevron. */
  children?: string;

  /** When `true`, applies a 1px border to the container. */
  border?: boolean;

  /** When `true`, forces the selected visual state. */
  selected?: boolean;

  /** When `true`, disables the button. */
  disabled?: boolean;

  /** URL to navigate to when clicked (renders an `<a>` internally). */
  href?: string;

  /** Tailwind group class for descendant hover utilities. */
  group?: string;

  /** When `true`, disables hover/active visual feedback. */
  static?: boolean;

  /** Click handler. */
  onClick?: React.MouseEventHandler<HTMLElement>;

  /** Height preset for the container. */
  heightVariant?: InteractiveContainerProps["heightVariant"];

  /** Padding preset for the container. */
  paddingVariant?: InteractiveContainerProps["paddingVariant"];

  /** Border-radius preset for the container. */
  roundingVariant?: InteractiveContainerProps["roundingVariant"];
};

// ---------------------------------------------------------------------------
// OpenButton
// ---------------------------------------------------------------------------

function OpenButton({
  open,
  icon: Icon,
  children,
  border,
  variant,
  subvariant,
  heightVariant,
  paddingVariant,
  roundingVariant,
  ...baseProps
}: OpenButtonProps) {
  // Derive open state: explicit prop → Radix data-state (injected via Slot chain)
  const dataState = (baseProps as Record<string, unknown>)["data-state"] as
    | string
    | undefined;
  const isOpen = open ?? dataState === "open";

  return (
    <Interactive.Base
      {...({ variant, subvariant } as InteractiveBaseVariantProps)}
      {...baseProps}
    >
      <Interactive.Container
        border={border}
        heightVariant={heightVariant}
        paddingVariant={paddingVariant}
        roundingVariant={roundingVariant}
      >
        <div className="opal-open-button interactive-foreground">
          {Icon && <Icon className="opal-open-button-icon" />}
          <div className="opal-open-button-content">{children}</div>
          <SvgChevronDownSmall
            className="opal-open-button-chevron"
            data-open={isOpen ? "true" : undefined}
            size={14}
          />
        </div>
      </Interactive.Container>
    </Interactive.Base>
  );
}

export { OpenButton, type OpenButtonProps };
