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
 * import Card from "@/refresh-components/Card";
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
 *   <Text headingH3>Section 1</Text>
 *   <Text body>Some content</Text>
 *   <Button>Action</Button>
 * </Card>
 * ```
 */

import { WithoutStyles } from "@/types";

export type CardProps = WithoutStyles<React.HTMLAttributes<HTMLDivElement>>;

export default function Card(props: CardProps) {
  return (
    <div
      className="bg-background-tint-00 p-4 flex flex-col gap-4 border rounded-16"
      {...props}
    />
  );
}
