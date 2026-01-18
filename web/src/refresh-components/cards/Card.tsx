/**
 * Card - A styled container component
 *
 * Provides a consistent card-style container with background, padding, border, and rounded corners.
 * Uses a vertical flex layout with automatic gap spacing between children.
 *
 * Features:
 * - Background color: background-tint-00
 * - Padding: 1rem (p-4)
 * - Flex column layout with 1rem gap (gap-4)
 * - Border with rounded-16 corners
 * - Accepts all standard div HTML attributes except className (enforced by WithoutStyles)
 * - Fixed styling - className prop not supported
 *
 * @example
 * ```tsx
 * import { Card } from "@/refresh-components/cards";
 *
 * // Basic usage
 * <Card>
 *   <h2>Card Title</h2>
 *   <p>Card content goes here</p>
 * </Card>
 *
 * // With onClick handler
 * <Card onClick={handleClick}>
 *   <div>Clickable card</div>
 * </Card>
 *
 * // Multiple children - automatically spaced
 * <Card>
 *   <Text as="p" headingH3>Section 1</Text>
 *   <Text as="p" body>Some content</Text>
 *   <Button>Action</Button>
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
  // card variants
  variant?: CardVariant;
  borderless?: boolean;

  ref?: React.Ref<HTMLDivElement>;
}

export default function Card({
  variant = "primary",
  borderless,
  padding = 1,
  ref,
  ...props
}: CardProps) {
  return (
    <div
      ref={ref}
      className="card"
      data-variant={variant}
      data-borderless={borderless || undefined}
    >
      <Section alignItems="start" padding={padding} height="fit" {...props} />
    </div>
  );
}
