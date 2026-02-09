import "@opal/components/buttons/OpenButton/styles.css";
import { Interactive, type InteractiveBaseProps } from "@opal/core";
import type { SizeVariant } from "@opal/components";
import { SvgChevronDownSmall } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type OpenButtonProps = InteractiveBaseProps & {
  /** Left icon component (renders at 1rem x 1rem). */
  icon?: IconFunctionComponent;

  /** Content rendered between the icon and chevron. */
  children?: string;

  /** When `true`, applies a 1px border to the container. */
  border?: boolean;

  /** Size preset — controls Container height/rounding/padding. */
  size?: SizeVariant;
};

// ---------------------------------------------------------------------------
// OpenButton
// ---------------------------------------------------------------------------

function OpenButton({
  icon: Icon,
  children,
  border,
  selected,
  size = "default",
  variant,
  subvariant,
  ...baseProps
}: OpenButtonProps) {
  // Derive open state: explicit prop → Radix data-state (injected via Slot chain)
  const dataState = (baseProps as Record<string, unknown>)["data-state"] as
    | string
    | undefined;
  const isOpen = selected ?? dataState === "open";
  const isCompact = size === "compact";

  return (
    <Interactive.Base
      {...({ variant, subvariant } as InteractiveBaseProps)}
      selected={selected}
      {...baseProps}
    >
      <Interactive.Container
        border={border}
        heightVariant={isCompact ? "compact" : "default"}
        roundingVariant={isCompact ? "compact" : "default"}
        paddingVariant={isCompact ? "thin" : "default"}
      >
        <div className="opal-open-button interactive-foreground">
          {Icon && <Icon className="opal-open-button-icon" />}
          <div className="opal-open-button-content">{children}</div>
          <SvgChevronDownSmall
            className="opal-open-button-chevron"
            data-selected={isOpen ? "true" : undefined}
            size={14}
          />
        </div>
      </Interactive.Container>
    </Interactive.Base>
  );
}

export { OpenButton, type OpenButtonProps };
