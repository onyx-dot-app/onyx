import "@opal/components/cards/select-card/styles.css";
import type { PaddingVariants, RoundingVariants } from "@opal/types";
import { paddingVariants, cardRoundingVariants } from "@opal/shared";
import { cn } from "@opal/utils";
import { Interactive, type InteractiveStatefulProps } from "@opal/core";
import type { BorderVariant } from "../card/components";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type SelectCardProps = Omit<InteractiveStatefulProps, "variant"> & {
  /**
   * Padding preset.
   *
   * | Value   | Class   |
   * |---------|---------|
   * | `"lg"`  | `p-6`   |
   * | `"md"`  | `p-4`   |
   * | `"sm"`  | `p-2`   |
   * | `"xs"`  | `p-1`   |
   * | `"2xs"` | `p-0.5` |
   * | `"fit"` | `p-0`   |
   *
   * @default "md"
   */
  padding?: PaddingVariants;

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
   * In the selected state, the border color changes to `border-action-link-05`.
   *
   * @default "solid"
   */
  border?: BorderVariant;

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
  padding: paddingProp = "md",
  rounding: roundingProp = "md",
  border = "solid",
  ref,
  children,
  ...statefulProps
}: SelectCardProps) {
  const padding = paddingVariants[paddingProp];
  const rounding = cardRoundingVariants[roundingProp];

  return (
    <Interactive.Stateful {...statefulProps} variant="select-card">
      <div
        ref={ref}
        className={cn("opal-select-card", padding, rounding)}
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
