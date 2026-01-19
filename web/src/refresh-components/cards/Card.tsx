/**
 * Card - A styled container component
 *
 * Provides a consistent card-style container with background, padding, border, and rounded corners.
 * Uses a vertical flex layout with automatic gap spacing between children.
 *
 * Features:
 * - Padding: 1rem by default (configurable)
 * - Flex column layout with 1rem gap
 * - Rounded-16 corners
 * - Accepts all standard div HTML attributes except className (enforced by WithoutStyles)
 *
 * Variants:
 * - `primary`: Solid background with border. The default, most prominent card style.
 * - `secondary`: Transparent background with border. Use for less prominent content or nested cards.
 * - `tertiary`: Transparent background with dashed border. Use for placeholder or empty states.
 * - `disabled`: Dimmed primary style with reduced opacity. Indicates unavailable or locked content.
 * - `borderless`: Solid background without border. Use when cards are visually grouped or in tight layouts.
 *
 * @example
 * ```tsx
 * import { Card } from "@/refresh-components/cards";
 *
 * // Basic usage (primary variant)
 * <Card>
 *   <h2>Card Title</h2>
 *   <p>Card content goes here</p>
 * </Card>
 *
 * // Secondary variant for nested content
 * <Card variant="secondary">
 *   <div>Less prominent content</div>
 * </Card>
 *
 * // Tertiary variant for empty states
 * <Card variant="tertiary">
 *   <div>No items yet</div>
 * </Card>
 * ```
 */

import { Section, SectionProps } from "@/layouts/general-layouts";

type CardVariant =
  // The main card variant.
  | "primary"
  // A background-colorless card variant.
  | "secondary"
  // A background-colorless card variant with a dashed border.
  | "tertiary"
  // A dimmed version of the primary variant (indicates that this card is unavailable).
  | "disabled"
  // A borderless version of the primary variant.
  | "borderless";

export interface CardProps extends SectionProps {
  // variants
  variant?: CardVariant;

  ref?: React.Ref<HTMLDivElement>;
}

export default function Card({
  variant = "primary",
  padding = 1,
  ref,
  ...props
}: CardProps) {
  return (
    <div ref={ref} className="card" data-variant={variant}>
      <Section alignItems="start" padding={padding} height="fit" {...props} />
    </div>
  );
}
