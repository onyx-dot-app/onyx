"use client";

import { cn } from "@/lib/utils";
import { WithoutStyles } from "@/types";

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

interface LabelProps
  extends WithoutStyles<
    // The `htmlFor` prop is instead renamed to `name?: string`.
    Omit<React.LabelHTMLAttributes<HTMLLabelElement>, "htmlFor">
  > {
  /** The name/id of the form element this label is associated with */
  name?: string;
  /** Whether the associated input is disabled */
  disabled?: boolean;
  nonInteractable?: boolean;
  ref?: React.Ref<HTMLLabelElement>;
}

export default function Label({
  name,
  disabled,
  nonInteractable,
  ref,
  ...props
}: LabelProps) {
  return (
    <label
      ref={ref}
      data-non-interactable={nonInteractable ? "true" : undefined}
      className={cn(
        "flex-1 self-stretch",
        "peer-disabled:cursor-not-allowed data-[non-interactable=true]:cursor-default",
        disabled
          ? "cursor-not-allowed"
          : nonInteractable
            ? undefined
            : "cursor-pointer"
      )}
      htmlFor={name}
      {...props}
    />
  );
}
