"use client";

import * as React from "react";
import { cn } from "@opal/utils";
import InputTypeIn, {
  InputTypeInProps,
} from "@/refresh-components/inputs/InputTypeIn";

/**
 * InputSearch Component
 *
 * A subtle search input that follows the "Subtle Input Styles" spec:
 * no border by default, border appears on hover/focus/active.
 *
 * @example
 * ```tsx
 * // Basic usage
 * <InputSearch
 *   placeholder="Search..."
 *   value={search}
 *   onChange={(e) => setSearch(e.target.value)}
 * />
 *
 * // Disabled state
 * <InputSearch
 *   disabled
 *   placeholder="Search..."
 *   value=""
 *   onChange={() => {}}
 * />
 * ```
 */
export interface InputSearchProps
  extends Omit<InputTypeInProps, "variant" | "leftSearchIcon"> {
  /**
   * Ref to the underlying input element.
   */
  ref?: React.Ref<HTMLInputElement>;
  /**
   * Whether the input is disabled.
   */
  disabled?: boolean;
}

export default function InputSearch({
  ref,
  disabled,
  className,
  ...props
}: InputSearchProps) {
  return (
    <InputTypeIn
      ref={ref}
      variant={disabled ? "disabled" : "internal"}
      leftSearchIcon
      className={cn(
        "[&_input]:font-main-ui-muted [&_input]:text-text-02 [&_input]:placeholder:text-text-02",
        !disabled && [
          "border border-transparent",
          "hover:border-border-03",
          "active:border-border-05",
          "focus-within:shadow-[0px_0px_0px_2px_var(--background-tint-04)]",
          "focus-within:hover:border-border-03",
        ],
        className
      )}
      {...props}
    />
  );
}
