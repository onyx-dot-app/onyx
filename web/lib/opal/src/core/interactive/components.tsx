import "@opal/core/interactive/styles.css";
import React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cn } from "@opal/utils";
import type { WithoutStyles } from "@opal/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type InteractiveBaseSelectVariantProps = {
  variant?: "select";
  subvariant?: "light" | "heavy";
  selected?: boolean;
};

/**
 * Discriminated union tying `variant` to `subvariant`.
 *
 * - `"none"` accepts no subvariant (`subvariant` must not be provided)
 * - `"select"` accepts an optional subvariant (defaults to `"light"`) and
 *   an optional `selected` boolean that switches foreground to action-link colours
 * - `"default"`, `"action"`, and `"danger"` accept an optional subvariant
 */
type InteractiveBaseVariantProps =
  | { variant?: "none"; subvariant?: never; selected?: never }
  | InteractiveBaseSelectVariantProps
  | {
      variant?: "default" | "action" | "danger";
      subvariant?: "primary" | "secondary" | "ghost";
      selected?: never;
    };

/**
 * Height presets for `Interactive.Container`.
 *
 * - `"default"` — Default height of 2.25rem (36px), suitable for most buttons/items
 * - `"compact"` — Reduced height of 1.75rem (28px), for denser UIs or inline elements
 * - `"fit"` — Shrink-wraps to content height (`h-fit`), for variable-height layouts
 */
type InteractiveContainerHeightVariant =
  keyof typeof interactiveContainerHeightVariants;
const interactiveContainerHeightVariants = {
  default: "h-[2.25rem]",
  compact: "h-[1.75rem]",
  fit: "h-fit",
} as const;
const interactiveContainerMinWidthVariants = {
  default: "min-w-[2.25rem]",
  compact: "min-w-[1.75rem]",
  fit: "",
} as const;

/**
 * Padding presets for `Interactive.Container`.
 *
 * - `"default"` — Default padding of 0.5rem (8px) on all sides
 * - `"thin"` — Reduced padding of 0.25rem (4px), for tighter layouts
 * - `"none"` — No padding, when the child handles its own spacing
 */
type InteractiveContainerPaddingVariant =
  keyof typeof interactiveContainerPaddingVariants;
const interactiveContainerPaddingVariants = {
  default: "p-2",
  thin: "p-1",
  none: "p-0",
} as const;

/**
 * Border-radius presets for `Interactive.Container`.
 *
 * - `"default"` — Default radius of 0.75rem (12px), matching card rounding
 * - `"compact"` — Smaller radius of 0.5rem (8px), for tighter/inline elements
 */
type InteractiveContainerRoundingVariant =
  keyof typeof interactiveContainerRoundingVariants;
const interactiveContainerRoundingVariants = {
  default: "rounded-12",
  compact: "rounded-08",
} as const;

// ---------------------------------------------------------------------------
// InteractiveBase
// ---------------------------------------------------------------------------

/**
 * Base props for {@link InteractiveBase} (without variant/subvariant).
 *
 * Extends standard HTML element attributes (minus `className` and `style`,
 * which are controlled by the design system).
 */
interface InteractiveBasePropsBase
  extends WithoutStyles<React.HTMLAttributes<HTMLElement>> {
  /**
   * Ref forwarded to the underlying element (the single child).
   * Since `Interactive.Base` uses Radix Slot, the ref attaches to whatever
   * element the child renders.
   */
  ref?: React.Ref<HTMLElement>;

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
   * When `true`, forces the transient (hover) visual state regardless of
   * actual pointer state.
   *
   * This sets `data-transient="true"` on the element, which the CSS uses to
   * apply the hover-state background and foreground. Useful for popover
   * triggers, toggle buttons, or any UI where you want to programmatically
   * indicate that the element is currently active.
   *
   * @default false
   */
  transient?: boolean;

  /**
   * When `true`, disables the interactive element.
   *
   * Sets `data-disabled` and `aria-disabled` attributes. CSS uses `data-disabled`
   * to apply disabled styles (muted colors, `cursor-not-allowed`). Click handlers
   * and `href` navigation are blocked in JS, but hover events still fire to
   * support tooltips explaining why the element is disabled.
   *
   * @default false
   */
  disabled?: boolean;

  /**
   * URL to navigate to when clicked.
   *
   * When provided, renders an `<a>` wrapper element instead of using Radix Slot.
   * The `<a>` receives all interactive styling (hover/active/transient states)
   * and children are rendered inside it.
   *
   * @example
   * ```tsx
   * <Interactive.Base href="/settings">
   *   <Interactive.Container border>
   *     <span>Go to Settings</span>
   *   </Interactive.Container>
   * </Interactive.Base>
   * ```
   */
  href?: string;

  /**
   * Link target (e.g. `"_blank"`). Only used when `href` is provided.
   */
  target?: string;
}

/**
 * Props for {@link InteractiveBase}.
 *
 * Intersects the base props with the {@link InteractiveBaseVariantProps}
 * discriminated union so that `variant` and `subvariant` are correlated:
 *
 * - `"none"` — `subvariant` must not be provided
 * - `"select"` — `subvariant` is optional (defaults to `"light"`); `selected` switches foreground to action-link colours
 * - `"default"` / `"action"` / `"danger"` — `subvariant` is optional (defaults to `"primary"`)
 */
type InteractiveBaseProps = InteractiveBasePropsBase &
  InteractiveBaseVariantProps;

/**
 * The foundational interactive surface primitive.
 *
 * `Interactive.Base` is the lowest-level building block for any clickable
 * element in the design system. It applies:
 *
 * 1. The `.interactive` CSS class (flex layout, pointer cursor, color transitions)
 * 2. `data-interactive-base-variant` and `data-interactive-base-subvariant`
 *    attributes for variant-specific background colors (both omitted for `"none"`;
 *    subvariant omitted when not provided)
 * 3. `data-static` attribute when hover feedback is disabled
 * 4. `data-transient` attribute for forced transient (hover) state
 * 5. `data-disabled` attribute for disabled styling
 *
 * All props are merged onto the single child element via Radix `Slot`, meaning
 * the child element *becomes* the interactive surface (no wrapper div).
 *
 * @example
 * ```tsx
 * // Basic usage with a container
 * <Interactive.Base variant="default" subvariant="primary">
 *   <Interactive.Container border>
 *     <span>Click me</span>
 *   </Interactive.Container>
 * </Interactive.Base>
 *
 * // Wrapping a component that controls its own background
 * <Interactive.Base variant="none" onClick={handleClick}>
 *   <Card>Card controls its own background</Card>
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
 *
 * // As a link
 * <Interactive.Base href="/settings">
 *   <Interactive.Container border>
 *     <span>Go to Settings</span>
 *   </Interactive.Container>
 * </Interactive.Base>
 * ```
 *
 * @see InteractiveBaseProps for detailed prop documentation
 */
function InteractiveBase({
  ref,
  variant = "default",
  subvariant,
  selected,
  group,
  static: isStatic,
  transient,
  disabled,
  href,
  target,
  ...props
}: InteractiveBaseProps) {
  const effectiveSubvariant =
    subvariant ?? (variant === "select" ? "light" : "primary");
  const classes = cn(
    "interactive",
    !props.onClick && !href && "!cursor-default !select-auto",
    group
  );

  const dataAttrs = {
    "data-interactive-base-variant": variant !== "none" ? variant : undefined,
    "data-interactive-base-subvariant":
      variant !== "none" ? effectiveSubvariant : undefined,
    "data-static": isStatic ? "true" : undefined,
    "data-transient": transient ? "true" : undefined,
    "data-selected": selected ? "true" : undefined,
    "data-disabled": disabled ? "true" : undefined,
    "aria-disabled": disabled || undefined,
  };

  if (href) {
    const { children, onClick, ...rest } = props;
    return (
      <a
        ref={ref as React.Ref<HTMLAnchorElement>}
        href={disabled ? undefined : href}
        target={target}
        rel={target === "_blank" ? "noopener noreferrer" : undefined}
        className={classes}
        {...dataAttrs}
        {...rest}
        onClick={
          disabled ? (e: React.MouseEvent) => e.preventDefault() : onClick
        }
      >
        {children}
      </a>
    );
  }

  const { onClick, ...slotProps } = props;
  return (
    <Slot
      ref={ref}
      className={classes}
      {...dataAttrs}
      {...slotProps}
      onClick={disabled ? undefined : onClick}
    />
  );
}

// ---------------------------------------------------------------------------
// InteractiveContainer
// ---------------------------------------------------------------------------

/**
 * Props for {@link InteractiveContainer}.
 *
 * Extends standard `<div>` attributes (minus `className` and `style`).
 */
interface InteractiveContainerProps
  extends WithoutStyles<React.HTMLAttributes<HTMLDivElement>> {
  /**
   * Ref forwarded to the underlying element.
   */
  ref?: React.Ref<HTMLElement>;

  /**
   * HTML button type (e.g. `"submit"`, `"button"`, `"reset"`).
   *
   * When provided, renders a `<button>` element instead of a `<div>`.
   * This keeps all styling (background, rounding, height) on a single
   * element — unlike a wrapper approach which would split them.
   *
   * @example
   * ```tsx
   * <Interactive.Base>
   *   <Interactive.Container type="submit">
   *     <span>Submit</span>
   *   </Interactive.Container>
   * </Interactive.Base>
   * ```
   */
  type?: "submit" | "button" | "reset";

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
   * - `"default"` — 0.75rem (12px), matching card-level rounding
   * - `"compact"` — 0.5rem (8px), for smaller/inline elements
   *
   * @default "default"
   */
  roundingVariant?: InteractiveContainerRoundingVariant;

  /**
   * Padding preset controlling inner spacing.
   *
   * - `"default"` — 0.5rem (8px) padding on all sides
   * - `"thin"` — 0.25rem (4px) padding for tighter layouts
   * - `"none"` — No padding; child content controls its own spacing
   *
   * @default "default"
   */
  paddingVariant?: InteractiveContainerPaddingVariant;

  /**
   * Height preset controlling the container's vertical size.
   *
   * - `"default"` — Fixed 2.25rem (36px), typical button/item height
   * - `"compact"` — Fixed 1.75rem (28px), for denser UIs
   * - `"full"` — Fills parent height (`h-full`)
   *
   * @default "default"
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
 * <Interactive.Base variant="default" subvariant="ghost">
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
  type,
  border,
  roundingVariant = "default",
  paddingVariant = "default",
  heightVariant = "default",
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
  const sharedProps = {
    ...rest,
    className: cn(
      "interactive-container",
      interactiveContainerRoundingVariants[roundingVariant],
      interactiveContainerPaddingVariants[paddingVariant],
      interactiveContainerHeightVariants[heightVariant],
      interactiveContainerMinWidthVariants[heightVariant],
      slotClassName
    ),
    "data-border": border ? ("true" as const) : undefined,
    style: slotStyle,
  };

  if (type) {
    // When Interactive.Base is disabled it injects aria-disabled via Slot.
    // Map that to the native disabled attribute so a <button type="submit">
    // cannot trigger form submission in the disabled state.
    const ariaDisabled = (rest as Record<string, unknown>)["aria-disabled"];
    const nativeDisabled =
      ariaDisabled === true || ariaDisabled === "true" || undefined;
    return (
      <button
        ref={ref as React.Ref<HTMLButtonElement>}
        type={type}
        disabled={nativeDisabled}
        {...(sharedProps as React.HTMLAttributes<HTMLButtonElement>)}
      />
    );
  }
  return <div ref={ref as React.Ref<HTMLDivElement>} {...sharedProps} />;
}

// ---------------------------------------------------------------------------
// Compound export
// ---------------------------------------------------------------------------

/**
 * Interactive compound component for building clickable surfaces.
 *
 * Provides two sub-components:
 *
 * - `Interactive.Base` — The foundational layer that applies hover/active/transient
 *   state styling via CSS data-attributes. Uses Radix Slot to merge onto child.
 *
 * - `Interactive.Container` — A structural `<div>` with design-system presets
 *   for border, padding, rounding, and height.
 *
 * @example
 * ```tsx
 * import { Interactive } from "@opal/core";
 *
 * <Interactive.Base variant="default" subvariant="ghost" onClick={handleClick}>
 *   <Interactive.Container border>
 *     <span>Clickable card</span>
 *   </Interactive.Container>
 * </Interactive.Base>
 * ```
 */
const Interactive = {
  Base: InteractiveBase,
  Container: InteractiveContainer,
};

export {
  Interactive,
  type InteractiveBaseProps,
  type InteractiveBaseVariantProps,
  type InteractiveBaseSelectVariantProps,
  type InteractiveContainerProps,
  type InteractiveContainerHeightVariant,
  type InteractiveContainerPaddingVariant,
  type InteractiveContainerRoundingVariant,
};
