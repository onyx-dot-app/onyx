import "@opal/components/cards/select-card/styles.css";
import type { ContainerSizeVariants } from "@opal/types";
import { containerSizeVariants } from "@opal/shared";
import { cn } from "@opal/utils";
import { Interactive, type InteractiveStatefulProps } from "@opal/core";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type SelectCardProps = InteractiveStatefulProps & {
  /**
   * Size preset — controls padding and border-radius.
   *
   * Padding comes from the shared size scale. Rounding follows the same
   * mapping as `Card` / `Button` / `Interactive.Container`:
   *
   * | Size       | Rounding     |
   * |------------|--------------|
   * | `lg`       | `rounded-16` |
   * | `md`–`sm`  | `rounded-12` |
   * | `xs`–`2xs` | `rounded-08` |
   * | `fit`      | `rounded-16` |
   *
   * @default "lg"
   */
  sizeVariant?: ContainerSizeVariants;

  /** Ref forwarded to the root `<div>`. */
  ref?: React.Ref<HTMLDivElement>;

  children?: React.ReactNode;
};

// ---------------------------------------------------------------------------
// Rounding
// ---------------------------------------------------------------------------

const roundingForSize: Record<ContainerSizeVariants, string> = {
  lg: "rounded-16",
  md: "rounded-12",
  sm: "rounded-12",
  xs: "rounded-08",
  "2xs": "rounded-08",
  fit: "rounded-16",
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
 * <SelectCard variant="select-heavy" state="selected" onClick={handleClick}>
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
  sizeVariant = "lg",
  ref,
  children,
  ...statefulProps
}: SelectCardProps) {
  const { padding } = containerSizeVariants[sizeVariant];
  const rounding = roundingForSize[sizeVariant];

  return (
    <Interactive.Stateful {...statefulProps}>
      <div ref={ref} className={cn("opal-select-card", padding, rounding)}>
        {children}
      </div>
    </Interactive.Stateful>
  );
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export { SelectCard, type SelectCardProps };
