import "@opal/components/cards/select-card/styles.css";
import type { BorderVariants, Rounding, Spacing } from "@opal/types";
import { roundingToRem, spacingToRem } from "@opal/shared";
import { cn } from "@opal/utils";
import { Interactive, type InteractiveStatefulProps } from "@opal/core";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type SelectCardProps = Omit<InteractiveStatefulProps, "variant"> & {
  /**
   * Padding.
   *
   * A spacing step: `N` is `N / 4` rem, so `4` is `1rem`.
   *
   * @default 4
   */
  padding?: Spacing;

  /**
   * Border-radius preset.
   *
   * `N` is `N / 4` rem, so `rounding={2}` is the same distance as
   * `padding={2}`. `"full"` is a pill.
   *
   * @default 3
   */
  rounding?: Rounding;

  /**
   * Border style.
   * - `"none"`: no border.
   * - `"dashed"`: dashed border.
   * - `"solid"`: solid border.
   *
   * @default "solid"
   */
  border?: BorderVariants;

  /** Ref forwarded to the root `<div>`. */
  ref?: React.Ref<HTMLDivElement>;

  children?: React.ReactNode;
};

// ---------------------------------------------------------------------------
// SelectCard
// ---------------------------------------------------------------------------

/**
 * A stateful interactive card — the card counterpart to `SelectButton`.
 *
 * Built on `Interactive.Stateful` (Slot) → a structural `<div>`. The
 * Stateful system owns background and foreground colors; the card owns
 * padding, rounding, border, and overflow.
 *
 * The root stays a `<div>` so children can be buttons and links, which HTML
 * forbids inside a `<button>`. A card with `onClick` is still a control: it
 * gets `role="button"`, joins the tab order, opens on Enter or Space, and
 * paints like hover while keyboard-focused.
 *
 * Children are fully composable — use `ContentAction`, `Content`, buttons,
 * `Interactive.Foldable`, etc. inside.
 *
 * @example
 * ```tsx
 * <SelectCard state="selected" onClick={handleClick}>
 *   <ContentAction
 *     icon={SvgGlobe}
 *     title="Google"
 *     description="Search engine"
 *     rightChildren={<Button>Set as Default</Button>}
 *   />
 * </SelectCard>
 * ```
 */
function SelectCard({
  padding: paddingProp = 4,
  rounding: roundingProp = 3,
  border = "solid",
  ref,
  children,
  onClick,
  onKeyDown,
  disabled,
  ...statefulProps
}: SelectCardProps) {
  const paddingStyle = { padding: spacingToRem(paddingProp) };
  const radius = roundingToRem(roundingProp);

  // A caller that assigns its own role (e.g. "radio" inside a radiogroup)
  // or tab index keeps it; the defaults only fill the gaps.
  const isControl = !!onClick && !disabled;
  const controlProps = isControl
    ? {
        role: statefulProps.role ?? "button",
        tabIndex: statefulProps.tabIndex ?? 0,
        onKeyDown: (event: React.KeyboardEvent<HTMLElement>) => {
          onKeyDown?.(event);
          if (event.defaultPrevented) return;
          // Keys pressed on a nested control belong to that control.
          if (event.target !== event.currentTarget) return;
          if (event.key !== "Enter" && event.key !== " ") return;
          event.preventDefault();
          event.currentTarget.click();
        },
      }
    : { onKeyDown };

  return (
    <Interactive.Stateful
      {...statefulProps}
      {...controlProps}
      onClick={onClick}
      disabled={disabled}
      variant="select-card"
    >
      <div
        ref={ref}
        className="opal-select-card"
        style={{ ...paddingStyle, borderRadius: radius }}
        data-border={border}
      >
        {children}
      </div>
    </Interactive.Stateful>
  );
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export { SelectCard, type SelectCardProps };
