import type { SVGProps } from "react";

/**
 * Base props for SVG icon components.
 *
 * Extends standard SVG element attributes with convenience props used across
 * the design system. All generated icon components (in `@opal/icons`) accept
 * this interface, ensuring a consistent API for sizing, coloring, and labeling.
 *
 * @example
 * ```tsx
 * import type { IconProps } from "@opal/types";
 *
 * function MyIcon({ size = 16, className, ...props }: IconProps) {
 *   return (
 *     <svg width={size} height={size} className={className} {...props}>
 *       ...
 *     </svg>
 *   );
 * }
 * ```
 */
export interface IconProps extends SVGProps<SVGSVGElement> {
  className?: string;
  size?: number;
  title?: string;
  color?: string;
}

/** Strips `className` and `style` from a props type to enforce design-system styling. */
export type WithoutStyles<T> = Omit<T, "className" | "style">;

/** Like `Omit` but distributes over union types, preserving discriminated unions. */
export type DistributiveOmit<T, K extends keyof any> = T extends any
  ? Omit<T, K>
  : never;

/**
 * A React function component that accepts {@link IconProps}.
 *
 * Use this type when a component prop expects an icon — it ensures the icon
 * supports `className`, `size`, `title`, and `color` without callers needing
 * to import `IconProps` directly.
 *
 * @example
 * ```tsx
 * import type { IconFunctionComponent } from "@opal/types";
 *
 * interface ButtonProps {
 *   icon?: IconFunctionComponent;
 * }
 * ```
 */
export type IconFunctionComponent = React.FunctionComponent<IconProps>;
