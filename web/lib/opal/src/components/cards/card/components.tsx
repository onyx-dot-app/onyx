import "@opal/components/cards/card/styles.css";
import type { SizeVariant } from "@opal/shared";
import { sizeVariants } from "@opal/shared";
import { cn } from "@opal/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type BackgroundVariant = "none" | "light" | "heavy";
type BorderVariant = "none" | "dashed" | "solid";

type CardProps = {
  /**
   * Size preset — controls padding and border-radius.
   *
   * Padding comes from the shared size scale. Rounding follows the same
   * mapping as `Button` / `Interactive.Container`:
   *
   * | Size   | Rounding   |
   * |--------|------------|
   * | `lg`   | `default`  |
   * | `md`–`sm` | `compact` |
   * | `xs`–`2xs` | `mini`  |
   * | `fit`  | `default`  |
   *
   * @default "lg"
   */
  sizeVariant?: SizeVariant;

  /**
   * Background fill intensity.
   * - `"none"`: transparent background.
   * - `"light"`: subtle tinted background (`bg-background-tint-00`).
   * - `"heavy"`: stronger tinted background (`bg-background-tint-01`).
   *
   * @default "light"
   */
  backgroundVariant?: BackgroundVariant;

  /**
   * Border style.
   * - `"none"`: no border.
   * - `"dashed"`: dashed border.
   * - `"solid"`: solid border.
   *
   * @default "none"
   */
  borderVariant?: BorderVariant;

  /** Ref forwarded to the root `<div>`. */
  ref?: React.Ref<HTMLDivElement>;

  children?: React.ReactNode;
  className?: string;
};

// ---------------------------------------------------------------------------
// Rounding
// ---------------------------------------------------------------------------

/** Maps a size variant to a rounding class, mirroring the Button pattern. */
const roundingForSize: Record<SizeVariant, string> = {
  lg: "rounded-12",
  md: "rounded-08",
  sm: "rounded-08",
  xs: "rounded-04",
  "2xs": "rounded-04",
  fit: "rounded-12",
};

// ---------------------------------------------------------------------------
// Card
// ---------------------------------------------------------------------------

function Card({
  sizeVariant = "lg",
  backgroundVariant = "light",
  borderVariant = "none",
  ref,
  children,
  className,
}: CardProps) {
  const { padding } = sizeVariants[sizeVariant];
  const rounding = roundingForSize[sizeVariant];

  return (
    <div
      ref={ref}
      className={cn("opal-card", padding, rounding, className)}
      data-background={backgroundVariant}
      data-border={borderVariant}
    >
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export { Card, type CardProps, type BackgroundVariant, type BorderVariant };
