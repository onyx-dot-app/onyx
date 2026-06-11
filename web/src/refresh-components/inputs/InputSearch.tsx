"use client";

import * as React from "react";
import { cn } from "@opal/utils";
import { InputTypeIn, type InputTypeInProps } from "@opal/components";

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
export interface InputSearchProps extends Omit<
  InputTypeInProps,
  "variant" | "searchIcon"
> {
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
  ...props
}: InputSearchProps) {
  return (
    <InputTypeIn
      ref={ref}
      variant={disabled ? "disabled" : "internal"}
      searchIcon
      {...props}
    />
  );
}
