"use client";

import { cn } from "@/lib/utils";

/**
 * Label - A form label component
 *
 * Renders a label element that associates with a form input via the `name` prop.
 *
 * @example
 * ```tsx
 * import Label from "@/refresh-components/form/Label";
 *
 * <Label name="email">
 *   Email Address
 * </Label>
 * ```
 */

interface LabelProps extends React.LabelHTMLAttributes<HTMLLabelElement> {
  /** The name/id of the form element this label is associated with */
  name?: string;
  /** Whether the associated input is disabled */
  disabled?: boolean;
  ref?: React.Ref<HTMLLabelElement>;
}

export default function Label({ name, disabled, ref, ...props }: LabelProps) {
  return (
    <label
      ref={ref}
      className={cn(
        "flex-1 self-stretch",
        disabled ? "cursor-not-allowed" : "cursor-pointer"
      )}
      htmlFor={name}
      {...props}
    />
  );
}
