import React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cn } from "@opal/utils";
import { SvgChevronDownSmall } from "@opal/icons";
import type { WithoutStyles } from "@opal/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Controls background color styling on the interactive element. */
export type InteractiveBaseVariant = "primary" | "secondary" | "tertiary";

/** Height presets for `Interactive.Container`. */
export type InteractiveContainerHeightVariant =
  keyof typeof interactiveContainerHeightVariants;
const interactiveContainerHeightVariants = {
  standard: "h-[2.25rem]",
  compact: "h-[1.75rem]",
  full: "h-full",
} as const;

/** Padding presets for `Interactive.Container`. */
export type InteractiveContainerPaddingVariant =
  keyof typeof interactiveContainerPaddingVariants;
const interactiveContainerPaddingVariants = {
  standard: "p-2",
  thin: "p-1",
  none: "p-0",
} as const;

/** Border-radius presets for `Interactive.Container`. */
export type InteractiveContainerRoundingVariant =
  keyof typeof interactiveContainerRoundingVariants;
const interactiveContainerRoundingVariants = {
  standard: "rounded-12",
  compact: "rounded-08",
} as const;

// ---------------------------------------------------------------------------
// InteractiveBase
// ---------------------------------------------------------------------------

export interface InteractiveBaseProps
  extends WithoutStyles<React.HTMLAttributes<HTMLElement>> {
  /** Ref to the underlying element. */
  ref?: React.Ref<HTMLElement>;
  /** Controls background color styling on the interactive element. */
  variant?: InteractiveBaseVariant;
  /**
   * Tailwind group class to apply (e.g. `"group/AgentCard"`).
   * Enables `group-hover` utilities on descendant elements.
   */
  group?: string;
  /** When true, disables hover/active visual feedback. */
  disableHover?: boolean;
  /** When true, forces the pressed visual state (same as `data-pressed="true"`). */
  transient?: boolean;
}

/**
 * The base interactive surface.
 *
 * Applies the `.interactive` CSS class and the appropriate data-attributes
 * for variant, non-interactive, and pressed states.
 *
 * @param props - See {@link InteractiveBaseProps}.
 *
 * @example
 * ```tsx
 * <Interactive.Base variant="secondary">
 *   <Interactive.Container border>
 *     <span>Hello</span>
 *   </Interactive.Container>
 * </Interactive.Base>
 * ```
 *
 * @remarks
 * Props are merged onto the single child element via Radix Slot.
 * The child element IS the interactive surface.
 * Hover styles are driven entirely by CSS selectors on `.interactive`.
 */
function InteractiveBase({
  ref,
  variant = "primary",
  group,
  disableHover,
  transient,
  ...props
}: InteractiveBaseProps) {
  const classes = cn("interactive", !props.onClick && "cursor-default", group);
  const dataAttrs = {
    "data-variant": variant,
    ...(disableHover && { "data-disable-hover": "true" as const }),
    ...(transient && { "data-pressed": "true" as const }),
  };

  return <Slot ref={ref} className={classes} {...dataAttrs} {...props} />;
}

// ---------------------------------------------------------------------------
// InteractiveContainer
// ---------------------------------------------------------------------------

export interface InteractiveContainerProps
  extends WithoutStyles<React.HTMLAttributes<HTMLDivElement>> {
  /** Ref to the underlying `<div>`. */
  ref?: React.Ref<HTMLDivElement>;
  /** Show a border around the container. */
  border?: boolean;
  /** Border-radius preset. @default "standard" */
  roundingVariant?: InteractiveContainerRoundingVariant;
  /** Padding preset. @default "standard" */
  paddingVariant?: InteractiveContainerPaddingVariant;
  /** Height preset. @default "standard" */
  heightVariant?: InteractiveContainerHeightVariant;
}

/**
 * Structural container used inside `Interactive.Base`.
 *
 * Provides border, padding, rounding, and height-variant presets.
 *
 * @param props - See {@link InteractiveContainerProps}.
 *
 * @example
 * ```tsx
 * <Interactive.Base>
 *   <Interactive.Container border heightVariant="compact">
 *     <SomeContent />
 *   </Interactive.Container>
 * </Interactive.Base>
 * ```
 *
 * @remarks
 * When used as a direct child of `Interactive.Base` (which uses Radix Slot),
 * Slot injects `className` and `style` at runtime — bypassing the
 * `WithoutStyles` compile-time guard. This component extracts and merges
 * those injected values so they are not lost.
 */
function InteractiveContainer({
  ref,
  border,
  roundingVariant = "standard",
  paddingVariant = "standard",
  heightVariant = "standard",
  ...props
}: InteractiveContainerProps) {
  // Radix Slot injects className and style at runtime (bypassing WithoutStyles),
  // so we extract and merge them to preserve the Slot-injected values.
  const {
    className: slotClassName,
    style: slotStyle,
    ...rest
  } = props as typeof props & {
    className?: string;
    style?: React.CSSProperties;
  };
  return (
    <div
      ref={ref}
      {...rest}
      className={cn(
        border && "border",
        interactiveContainerRoundingVariants[roundingVariant],
        interactiveContainerPaddingVariants[paddingVariant],
        interactiveContainerHeightVariants[heightVariant],
        slotClassName
      )}
      style={slotStyle}
    />
  );
}

// ---------------------------------------------------------------------------
// InteractiveChevronContainer
// ---------------------------------------------------------------------------

export interface InteractiveChevronContainerProps
  extends InteractiveContainerProps {
  /** Explicit open state. When omitted, falls back to Radix `data-state`. */
  open?: boolean;
}

/**
 * Like `Interactive.Container`, but renders a chevron-down icon on the right
 * that rotates 180° when "open".
 *
 * @param props - See {@link InteractiveChevronContainerProps}.
 *
 * @example
 * ```tsx
 * <Popover>
 *   <Popover.Trigger asChild>
 *     <Interactive.Base>
 *       <Interactive.ChevronContainer>
 *         <LineItemLayout icon={SvgIcon} title="Option" variant="secondary" center />
 *       </Interactive.ChevronContainer>
 *     </Interactive.Base>
 *   </Popover.Trigger>
 *   <Popover.Content>…</Popover.Content>
 * </Popover>
 * ```
 *
 * @remarks
 * Open state is resolved in order:
 * 1. Explicit `open` prop
 * 2. Radix `data-state` attribute (injected through the Slot chain by
 *    `Popover.Trigger` → `Interactive.Base` → this component)
 */
function InteractiveChevronContainer({
  open,
  children,
  ...containerProps
}: InteractiveChevronContainerProps) {
  // Derive open state: explicit prop → Radix data-state (injected via Slot chain)
  const dataState = (containerProps as Record<string, unknown>)[
    "data-state"
  ] as string | undefined;
  const isOpen = open ?? dataState === "open";

  return (
    <InteractiveContainer {...containerProps}>
      <div className="flex flex-row items-center gap-2">
        <div className="flex-1 min-w-0">{children}</div>
        <SvgChevronDownSmall
          className={cn(
            "shrink-0 transition-transform duration-200",
            isOpen && "-rotate-180"
          )}
          size={14}
        />
      </div>
    </InteractiveContainer>
  );
}

// ---------------------------------------------------------------------------
// Compound export
// ---------------------------------------------------------------------------

const Interactive = {
  Base: InteractiveBase,
  Container: InteractiveContainer,
  ChevronContainer: InteractiveChevronContainer,
};

export { Interactive };
