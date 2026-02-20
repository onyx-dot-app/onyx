import "@opal/core/interactive/styles.css";
import React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cn } from "@opal/utils";
import type { WithoutStyles } from "@opal/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type InteractiveBaseVariantTypes = "default" | "action" | "danger";
type InteractiveBaseProminenceTypes =
  | "primary"
  | "secondary"
  | "tertiary"
  | "internal";
type InteractiveBaseSelectVariantProps = {
  variant?: "select";
  prominence?: "light" | "heavy";
  selected?: boolean;
};

/**
 * Discriminated union tying `variant` to `prominence`.
 *
 * - `"none"` accepts no prominence (`prominence` must not be provided)
 * - `"select"` accepts an optional prominence (defaults to `"light"`) and
 *   an optional `selected` boolean that switches foreground to action-link colours
 * - `"default"`, `"action"`, and `"danger"` accept an optional prominence
 *   (defaults to `"primary"`)
 */
type InteractiveBaseVariantProps =
  | { variant?: "none"; prominence?: never; selected?: never }
  | InteractiveBaseSelectVariantProps
  | {
      variant?: InteractiveBaseVariantTypes;
      prominence?: InteractiveBaseProminenceTypes;
      selected?: never;
    };

/**
 * Height presets for `Interactive.Container`.
 *
 * - `"lg"` — 2.25rem (36px), suitable for most buttons/items
 * - `"md"` — 1.75rem (28px), standard compact size
 * - `"sm"` — 1.5rem (24px), for denser UIs
 * - `"xs"` — 1.25rem (20px), for inline elements
 * - `"2xs"` — 1rem (16px), for micro elements
 * - `"fit"` — Shrink-wraps to content height (`h-fit`), for variable-height layouts
 */
type InteractiveContainerHeightVariant =
  keyof typeof interactiveContainerSizeVariants;
const interactiveContainerSizeVariants = {
  lg: { height: "h-[2.25rem]", minWidth: "min-w-[2.25rem]", padding: "p-2" },
  md: { height: "h-[1.75rem]", minWidth: "min-w-[1.75rem]", padding: "p-1" },
  sm: { height: "h-[1.5rem]", minWidth: "min-w-[1.5rem]", padding: "p-1" },
  xs: {
    height: "h-[1.25rem]",
    minWidth: "min-w-[1.25rem]",
    padding: "p-0.5",
  },
  "2xs": { height: "h-[1rem]", minWidth: "min-w-[1rem]", padding: "p-0.5" },
  fit: { height: "h-fit", minWidth: "", padding: "p-0" },
} as const;

/**
 * Width presets for `Interactive.Container`.
 *
 * - `"auto"` — Shrink-wraps to content width (default)
 * - `"full"` — Stretches to fill the parent's width (`w-full`)
 */
type InteractiveContainerWidthVariant = "auto" | "full";
const interactiveContainerWidthVariants = {
  auto: "w-auto",
  full: "w-full",
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
  mini: "rounded-04",
} as const;

// ---------------------------------------------------------------------------
// InteractiveBase
// ---------------------------------------------------------------------------

/**
 * Base props for {@link InteractiveBase} (without variant/prominence).
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
   * Passed through Slot to the child element (typically `Interactive.Container`),
   * which renders an `<a>` tag when `href` is present. This keeps all styling
   * (backgrounds, rounding, overflow) on a single element.
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
 * discriminated union so that `variant` and `prominence` are correlated:
 *
 * - `"none"` — `prominence` must not be provided
 * - `"select"` — `prominence` is optional (defaults to `"light"`); `selected` switches foreground to action-link colours
 * - `"default"` / `"action"` / `"danger"` — `prominence` is optional (defaults to `"primary"`)
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
 * 2. `data-interactive-base-variant` and `data-interactive-base-prominence`
 *    attributes for variant-specific background colors (both omitted for `"none"`;
 *    prominence omitted when not provided)
 * 3. `data-transient` attribute for forced transient (hover) state
 * 4. `data-disabled` attribute for disabled styling
 *
 * All props are merged onto the single child element via Radix `Slot`, meaning
 * the child element *becomes* the interactive surface (no wrapper div).
 *
 * @example
 * ```tsx
 * // Basic usage with a container
 * <Interactive.Base variant="default" prominence="primary">
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
  prominence,
  selected,
  group,
  transient,
  disabled,
  href,
  target,
  ...props
}: InteractiveBaseProps) {
  const effectiveProminence =
    prominence ?? (variant === "select" ? "light" : "primary");
  const classes = cn(
    "interactive",
    !props.onClick && !href && "!cursor-default !select-auto",
    group
  );

  const dataAttrs = {
    "data-interactive-base-variant": variant !== "none" ? variant : undefined,
    "data-interactive-base-prominence":
      variant !== "none" ? effectiveProminence : undefined,
    "data-transient": transient ? "true" : undefined,
    "data-selected": selected ? "true" : undefined,
    "data-disabled": disabled ? "true" : undefined,
    "aria-disabled": disabled || undefined,
  };

  const { onClick, ...slotProps } = props;

  // href, target, and rel are passed through Slot to the child element
  // (typically Interactive.Container), which renders an <a> when href is present.
  const linkAttrs = href
    ? {
        href: disabled ? undefined : href,
        target,
        rel: target === "_blank" ? "noopener noreferrer" : undefined,
      }
    : {};

  return (
    <Slot
      ref={ref}
      className={classes}
      {...dataAttrs}
      {...linkAttrs}
      {...slotProps}
      onClick={
        disabled && href
          ? (e: React.MouseEvent) => e.preventDefault()
          : disabled
            ? undefined
            : onClick
      }
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
   * Mutually exclusive with `href`.
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
   * Height preset controlling the container's vertical size.
   *
   * - `"lg"` — 2.25rem (36px), typical button/item height
   * - `"md"` — 1.75rem (28px), standard compact size
   * - `"sm"` — 1.5rem (24px), for denser UIs
   * - `"xs"` — 1.25rem (20px), for inline elements
   * - `"2xs"` — 1rem (16px), for micro elements
   * - `"fit"` — Shrink-wraps to content height (`h-fit`)
   *
   * @default "lg"
   */
  heightVariant?: InteractiveContainerHeightVariant;

  /**
   * Width preset controlling the container's horizontal size.
   *
   * - `"auto"` — Shrink-wraps to content width
   * - `"full"` — Stretches to fill the parent's width (`w-full`)
   *
   * @default "auto"
   */
  widthVariant?: InteractiveContainerWidthVariant;
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
 *     <Content icon={SvgIcon} title="Option" />
 *   </Interactive.Container>
 * </Interactive.Base>
 *
 * // Compact, borderless container with no padding
 * <Interactive.Base variant="default" prominence="tertiary">
 *   <Interactive.Container heightVariant="md" roundingVariant="compact">
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
  heightVariant = "lg",
  widthVariant = "auto",
  ...props
}: InteractiveContainerProps) {
  // Radix Slot injects className, style, href, target, rel, and other
  // attributes at runtime (bypassing WithoutStyles), so we extract and
  // merge them to preserve the Slot-injected values.
  const {
    className: slotClassName,
    style: slotStyle,
    href,
    target,
    rel,
    ...rest
  } = props as typeof props & {
    className?: string;
    style?: React.CSSProperties;
    href?: string;
    target?: string;
    rel?: string;
  };
  const { height, minWidth, padding } =
    interactiveContainerSizeVariants[heightVariant];
  const sharedProps = {
    ...rest,
    className: cn(
      "interactive-container",
      interactiveContainerRoundingVariants[roundingVariant],
      height,
      minWidth,
      padding,
      interactiveContainerWidthVariants[widthVariant],
      slotClassName
    ),
    "data-border": border ? ("true" as const) : undefined,
    style: slotStyle,
  };

  // When href is provided (via Slot from Interactive.Base), render an <a>
  // so all styling (backgrounds, rounding, overflow) lives on one element.
  if (href) {
    return (
      <a
        ref={ref as React.Ref<HTMLAnchorElement>}
        href={href}
        target={target}
        rel={rel}
        {...(sharedProps as React.HTMLAttributes<HTMLAnchorElement>)}
      />
    );
  }

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
 * <Interactive.Base variant="default" prominence="tertiary" onClick={handleClick}>
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
  type InteractiveContainerWidthVariant,
  type InteractiveContainerRoundingVariant,
};
