import "@opal/components/cards/shared.css";
import "@opal/components/cards/card/styles.css";
import type {
  PaddingVariants,
  RoundingVariants,
  StatusVariants,
} from "@opal/types";
import { paddingVariants, cardRoundingVariants } from "@opal/shared";
import { cn } from "@opal/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type BackgroundVariant = "none" | "light" | "heavy";
type BorderVariant = "none" | "dashed" | "solid";

type CardProps = {
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
   * Background fill intensity.
   * - `"none"`: transparent background.
   * - `"light"`: subtle tinted background (`bg-background-tint-00`).
   * - `"heavy"`: stronger tinted background (`bg-background-tint-01`).
   *
   * @default "light"
   */
  background?: BackgroundVariant;

  /**
   * Border style.
   * - `"none"`: no border.
   * - `"dashed"`: dashed border.
   * - `"solid"`: solid border.
   *
   * @default "none"
   */
  border?: BorderVariant;

  /**
   * Border color, drawn from the same status palette as {@link MessageCard}.
   * Has no visual effect when `border="none"`.
   *
   * @default "default"
   */
  borderColor?: StatusVariants;

  /** Ref forwarded to the root `<div>`. */
  ref?: React.Ref<HTMLDivElement>;

  children?: React.ReactNode;
};

// ---------------------------------------------------------------------------
// Card
// ---------------------------------------------------------------------------

function Card({
  padding: paddingProp = "md",
  rounding: roundingProp = "md",
  background = "light",
  border = "none",
  borderColor = "default",
  ref,
  children,
}: CardProps) {
  const padding = paddingVariants[paddingProp];
  const rounding = cardRoundingVariants[roundingProp];

  return (
    <div
      ref={ref}
      className={cn("opal-card", padding, rounding)}
      data-background={background}
      data-border={border}
      data-opal-status-border={borderColor}
    >
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export { Card, type CardProps, type BackgroundVariant, type BorderVariant };
