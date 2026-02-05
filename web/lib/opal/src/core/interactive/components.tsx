import React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cn } from "@opal/utils";
import { SvgChevronDownSmall } from "@opal/icons";
import type { WithoutStyles } from "@opal/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * Background color variant for interactive elements.
 *
 * Each variant defines a base background tint and corresponding hover/active
 * state colors, providing visual hierarchy across the UI:
 *
 * - `"primary"` — Lightest tint (`tint-00`), used for primary surfaces
 * - `"secondary"` — Medium tint (`tint-01`), used for secondary/nested surfaces
 * - `"tertiary"` — Darker tint (`tint-02`), used for tertiary/emphasized surfaces
 */
export type InteractiveBaseVariant = "primary" | "secondary" | "tertiary";

/**
 * Height presets for `Interactive.Container`.
 *
 * - `"standard"` — Default height of 2.25rem (36px), suitable for most buttons/items
 * - `"compact"` — Reduced height of 1.75rem (28px), for denser UIs or inline elements
 * - `"full"` — Expands to fill parent height (`h-full`), for flexible layouts
 */
export type InteractiveContainerHeightVariant =
  keyof typeof interactiveContainerHeightVariants;
const interactiveContainerHeightVariants = {
  standard: "h-[2.25rem]",
  compact: "h-[1.75rem]",
  full: "h-full",
} as const;

/**
 * Padding presets for `Interactive.Container`.
 *
 * - `"standard"` — Default padding of 0.5rem (8px) on all sides
 * - `"thin"` — Reduced padding of 0.25rem (4px), for tighter layouts
 * - `"none"` — No padding, when the child handles its own spacing
 */
export type InteractiveContainerPaddingVariant =
  keyof typeof interactiveContainerPaddingVariants;
const interactiveContainerPaddingVariants = {
  standard: "p-2",
  thin: "p-1",
  none: "p-0",
} as const;

/**
 * Border-radius presets for `Interactive.Container`.
 *
 * - `"standard"` — Default radius of 0.75rem (12px), matching card rounding
 * - `"compact"` — Smaller radius of 0.5rem (8px), for tighter/inline elements
 */
export type InteractiveContainerRoundingVariant =
  keyof typeof interactiveContainerRoundingVariants;
const interactiveContainerRoundingVariants = {
  standard: "rounded-12",
  compact: "rounded-08",
} as const;

// ---------------------------------------------------------------------------
// InteractiveBase
// ---------------------------------------------------------------------------

/**
 * Props for {@link InteractiveBase}.
 *
 * Extends standard HTML element attributes (minus `className` and `style`,
 * which are controlled by the design system).
 */
export interface InteractiveBaseProps
  extends WithoutStyles<React.HTMLAttributes<HTMLElement>> {
  /**
   * Ref forwarded to the underlying element (the single child).
   * Since `Interactive.Base` uses Radix Slot, the ref attaches to whatever
   * element the child renders.
   */
  ref?: React.Ref<HTMLElement>;

  /**
   * Background color variant controlling the base tint and hover/active states.
   *
   * - `"primary"` — Base `tint-00`, hover `tint-02`, active `tint-00`
   * - `"secondary"` — Base `tint-01`, hover `tint-02`, active `tint-00`
   * - `"tertiary"` — Base `tint-02`, hover `tint-03`, active `tint-00`
   *
   * @default "primary"
   */
  variant?: InteractiveBaseVariant;

  /**
   * Tailwind group class to apply (e.g. `"group/AgentCard"`).
   *
   * When set, this class is added to the element, enabling `group-hover:*`
   * utilities on descendant elements. Useful for showing/hiding child elements
   * (like action buttons) when the interactive surface is hovered.
   *
   * @example
   * ```tsx
   * <Interactive.Base group="group/Card">
   *   <Card>
   *     <IconButton className="hidden group-hover/Card:flex" />
   *   </Card>
   * </Interactive.Base>
   * ```
   */
  group?: string;

  /**
   * When `true`, disables all hover and active visual feedback.
   *
   * The element still renders with its base variant color and remains
   * interactive (clicks still fire), but the CSS `:hover` and `:active`
   * state changes are suppressed via `data-static` attribute.
   *
   * Use this for elements that need the interactive styling structure but
   * shouldn't visually respond to pointer events (e.g., a card that handles
   * clicks internally but shouldn't highlight on hover).
   *
   * @default false
   */
  static?: boolean;

  /**
   * When `true`, forces the pressed/active visual state regardless of
   * actual pointer state.
   *
   * This sets `data-pressed="true"` on the element, which the CSS uses to
   * apply the active-state background. Useful for toggle buttons, selected
   * states, or any UI where you want to programmatically show "pressed"
   * appearance.
   *
   * @default false
   */
  transient?: boolean;
}

/**
 * The foundational interactive surface primitive.
 *
 * `Interactive.Base` is the lowest-level building block for any clickable
 * element in the design system. It applies:
 *
 * 1. The `.interactive` CSS class (flex layout, pointer cursor, no text selection)
 * 2. `data-variant` attribute for variant-specific background colors
 * 3. `data-static` attribute when hover feedback is disabled
 * 4. `data-pressed` attribute for forced pressed state
 *
 * All props are merged onto the single child element via Radix `Slot`, meaning
 * the child element *becomes* the interactive surface (no wrapper div).
 *
 * @example
 * ```tsx
 * // Basic usage with a container
 * <Interactive.Base variant="secondary">
 *   <Interactive.Container border>
 *     <span>Click me</span>
 *   </Interactive.Container>
 * </Interactive.Base>
 *
 * // With group hover for child visibility
 * <Interactive.Base group="group/Item" onClick={handleClick}>
 *   <div>
 *     <span>Item</span>
 *     <button className="hidden group-hover/Item:block">Delete</button>
 *   </div>
 * </Interactive.Base>
 *
 * // Static (no hover feedback)
 * <Interactive.Base static>
 *   <Card>Content that doesn't highlight on hover</Card>
 * </Interactive.Base>
 * ```
 *
 * @see InteractiveBaseProps for detailed prop documentation
 */
function InteractiveBase({
  ref,
  variant = "primary",
  group,
  static: isStatic,
  transient,
  ...props
}: InteractiveBaseProps) {
  const classes = cn("interactive", !props.onClick && "cursor-default", group);
  const dataAttrs = {
    "data-variant": variant,
    ...(isStatic && { "data-static": "true" as const }),
    ...(transient && { "data-pressed": "true" as const }),
  };

  return <Slot ref={ref} className={classes} {...dataAttrs} {...props} />;
}

// ---------------------------------------------------------------------------
// InteractiveContainer
// ---------------------------------------------------------------------------

/**
 * Props for {@link InteractiveContainer}.
 *
 * Extends standard `<div>` attributes (minus `className` and `style`).
 */
export interface InteractiveContainerProps
  extends WithoutStyles<React.HTMLAttributes<HTMLDivElement>> {
  /**
   * Ref forwarded to the underlying `<div>` element.
   */
  ref?: React.Ref<HTMLDivElement>;

  /**
   * When `true`, applies a 1px border using the theme's border color.
   *
   * The border uses the default `border` utility class, which references
   * the `--border` CSS variable for consistent theming.
   *
   * @default false
   */
  border?: boolean;

  /**
   * Border-radius preset controlling corner rounding.
   *
   * - `"standard"` — 0.75rem (12px), matching card-level rounding
   * - `"compact"` — 0.5rem (8px), for smaller/inline elements
   *
   * @default "standard"
   */
  roundingVariant?: InteractiveContainerRoundingVariant;

  /**
   * Padding preset controlling inner spacing.
   *
   * - `"standard"` — 0.5rem (8px) padding on all sides
   * - `"thin"` — 0.25rem (4px) padding for tighter layouts
   * - `"none"` — No padding; child content controls its own spacing
   *
   * @default "standard"
   */
  paddingVariant?: InteractiveContainerPaddingVariant;

  /**
   * Height preset controlling the container's vertical size.
   *
   * - `"standard"` — Fixed 2.25rem (36px), typical button/item height
   * - `"compact"` — Fixed 1.75rem (28px), for denser UIs
   * - `"full"` — Fills parent height (`h-full`)
   *
   * @default "standard"
   */
  heightVariant?: InteractiveContainerHeightVariant;
}

/**
 * Structural container for use inside `Interactive.Base`.
 *
 * Provides a `<div>` with design-system-controlled border, padding, rounding,
 * and height. Use this when you need a consistent container shape for
 * interactive content.
 *
 * When nested directly under `Interactive.Base`, Radix Slot merges the parent's
 * `className` and `style` onto this component at runtime. This component
 * correctly extracts and merges those injected values so they aren't lost.
 *
 * @example
 * ```tsx
 * // Standard card-like container
 * <Interactive.Base>
 *   <Interactive.Container border>
 *     <LineItemLayout icon={SvgIcon} title="Option" />
 *   </Interactive.Container>
 * </Interactive.Base>
 *
 * // Compact, borderless container with no padding
 * <Interactive.Base variant="secondary">
 *   <Interactive.Container
 *     heightVariant="compact"
 *     roundingVariant="compact"
 *     paddingVariant="none"
 *   >
 *     <span>Inline item</span>
 *   </Interactive.Container>
 * </Interactive.Base>
 * ```
 *
 * @see InteractiveContainerProps for detailed prop documentation
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

/**
 * Props for {@link InteractiveChevronContainer}.
 *
 * Extends all `InteractiveContainerProps` with an additional `open` prop.
 */
export interface InteractiveChevronContainerProps
  extends InteractiveContainerProps {
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
}

/**
 * Container with an animated chevron indicator for expandable/collapsible UI.
 *
 * Extends `Interactive.Container` by adding a chevron-down icon on the right
 * side that rotates 180° when the element is "open". Commonly used for:
 *
 * - Popover triggers
 * - Dropdown menus
 * - Accordion headers
 * - Any expandable section
 *
 * The open state is determined by (in order of precedence):
 * 1. The explicit `open` prop
 * 2. Radix `data-state="open"` attribute (auto-injected by Radix primitives)
 *
 * This means it works automatically when used with Radix `Popover.Trigger`,
 * `DropdownMenu.Trigger`, etc., without any extra wiring.
 *
 * @example
 * ```tsx
 * // With Radix Popover (automatic open state)
 * <Popover>
 *   <Popover.Trigger asChild>
 *     <Interactive.Base>
 *       <Interactive.ChevronContainer border>
 *         <span>Select option</span>
 *       </Interactive.ChevronContainer>
 *     </Interactive.Base>
 *   </Popover.Trigger>
 *   <Popover.Content>...</Popover.Content>
 * </Popover>
 *
 * // With explicit open control
 * <Interactive.Base onClick={() => setOpen(!open)}>
 *   <Interactive.ChevronContainer open={open}>
 *     <span>Toggle section</span>
 *   </Interactive.ChevronContainer>
 * </Interactive.Base>
 * ```
 *
 * @see InteractiveChevronContainerProps for detailed prop documentation
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

/**
 * Interactive compound component for building clickable surfaces.
 *
 * Provides three sub-components:
 *
 * - `Interactive.Base` — The foundational layer that applies hover/active/pressed
 *   state styling via CSS data-attributes. Uses Radix Slot to merge onto child.
 *
 * - `Interactive.Container` — A structural `<div>` with design-system presets
 *   for border, padding, rounding, and height.
 *
 * - `Interactive.ChevronContainer` — Like `Container` but with an animated
 *   chevron icon for expandable UI (popovers, dropdowns, accordions).
 *
 * @example
 * ```tsx
 * import { Interactive } from "@opal/core";
 *
 * <Interactive.Base variant="secondary" onClick={handleClick}>
 *   <Interactive.Container border>
 *     <span>Clickable card</span>
 *   </Interactive.Container>
 * </Interactive.Base>
 * ```
 */
const Interactive = {
  Base: InteractiveBase,
  Container: InteractiveContainer,
  ChevronContainer: InteractiveChevronContainer,
};

export { Interactive };
