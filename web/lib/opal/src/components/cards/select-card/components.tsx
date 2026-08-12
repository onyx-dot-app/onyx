import "@opal/components/cards/select-card/styles.css";
import type { BorderVariants, Spacing, RoundingVariants } from "@opal/types";
import { cardRoundingVariants, spacingToRem } from "@opal/shared";
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
   * | Value  | Class        |
   * |--------|--------------|
   * | `"xs"` | `rounded-04` |
   * | `"sm"` | `rounded-08` |
   * | `"md"` | `rounded-12` |
   * | `"lg"` | `rounded-16` |
   *
   * @default "md"
   */
  rounding?: RoundingVariants;

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
  rounding: roundingProp = "md",
  border = "solid",
  ref,
  children,
  ...statefulProps
}: SelectCardProps) {
  const paddingStyle = { padding: spacingToRem(paddingProp) };
  const rounding = cardRoundingVariants[roundingProp];

  return (
    <Interactive.Stateful {...statefulProps} variant="select-card">
      <div
        ref={ref}
        className={cn("opal-select-card", rounding)}
        style={paddingStyle}
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
