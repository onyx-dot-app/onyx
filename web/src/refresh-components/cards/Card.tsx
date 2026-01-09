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

import { cn } from "@/lib/utils";
import * as GeneralLayouts from "@/layouts/general-layouts";

const classNames = {
  main: ["bg-background-tint-00 border"],
  translucent: ["bg-transparent border border-dashed"],
  disabled: [
    "cursor-not-allowed pointer-events-none bg-background-tint-00 border opacity-50",
  ],
} as const;

export interface CardProps extends GeneralLayouts.SectionProps {
  // card variants
  translucent?: boolean;
  disabled?: boolean;
}

export default function Card({
  translucent,
  disabled,

  padding = 1,

  ...props
}: CardProps) {
  const variant = translucent ? "translucent" : disabled ? "disabled" : "main";

  return (
    <div className={cn("rounded-16 w-full h-full", classNames[variant])}>
      <GeneralLayouts.Section alignItems="start" padding={padding} {...props} />
    </div>
  );
}
