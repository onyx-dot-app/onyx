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
 * - Accepts all standard div HTML attributes
 * - Supports className overrides for customization
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
 * // With custom className
 * <Card className="max-w-md">
 *   <div>Custom styled card</div>
 * </Card>
 *
 * // With onClick handler
 * <Card onClick={handleClick} className="cursor-pointer hover:opacity-80">
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

import { cn } from "@/lib/utils";

export default function Card({
  children,
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "bg-background-tint-00 p-4 flex flex-col gap-4 border rounded-16",
        className
      )}
      {...props}
    >
      {children}
    </div>
  );
}
