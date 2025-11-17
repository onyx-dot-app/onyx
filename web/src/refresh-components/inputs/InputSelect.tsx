"use client";

import React, { useState, useRef } from "react";
import { cn } from "@/lib/utils";
import * as SelectPrimitive from "@radix-ui/react-select";
import SvgChevronDownSmall from "@/icons/chevron-down-small";
import { useClickOutside } from "@/lib/hooks";

const triggerClasses = {
  main: ["border", "hover:border-border-02", "active:!border-border-05"],
  internal: [],
  error: ["border", "border-status-error-05"],
  disabled: ["bg-background-neutral-03"],
} as const;

const valueClasses = {
  main: [
    "text-text-04 placeholder:!font-secondary-body placeholder:text-text-02",
  ],
  internal: [],
  disabled: ["text-text-02"],
} as const;

export interface InputSelectOption {
  value: string;
  label: string;
  description?: string;
  disabled?: boolean;
}

export interface InputSelectProps
  extends Omit<
    React.ComponentPropsWithoutRef<typeof SelectPrimitive.Trigger>,
    "value" | "onValueChange" | "disabled"
  > {
  // Input states:
  internal?: boolean;
  error?: boolean;
  disabled?: boolean;

  // Select specific props
  value?: string;
  onValueChange?: (value: string) => void;
  options: InputSelectOption[];
  placeholder?: string;

  // Right section of the input, e.g. action button
  rightSection?: React.ReactNode;
}

export default function InputSelect({
  internal,
  error,
  disabled,

  value,
  onValueChange,
  options,
  placeholder = "Select an option",
  rightSection,
  onClick,
  className,
  ...props
}: InputSelectProps) {
  const variant = internal ? "internal" : disabled ? "disabled" : "main";

  const [isOpen, setIsOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Close dropdown when clicking outside
  useClickOutside(() => setIsOpen(false), [triggerRef, dropdownRef], isOpen);

  function handleTriggerClick(event: React.MouseEvent<HTMLButtonElement>) {
    event.preventDefault();
    setIsOpen(!isOpen);
    onClick?.(event);
  }

  return (
    <div className="relative w-full">
      <SelectPrimitive.Root
        value={value}
        onValueChange={onValueChange}
        disabled={disabled}
      >
        <SelectPrimitive.Trigger
          ref={triggerRef}
          className={cn(
            "group/InputSelect flex-1 flex w-full items-center justify-between p-1.5 rounded-08 bg-background-neutral-00 hover:cursor-pointer disabled:cursor-not-allowed",
            triggerClasses[variant],
            className
          )}
          onClick={handleTriggerClick}
          {...props}
        >
          <div
            className={cn(
              "flex flex-row items-center justify-between w-full p-0.5 gap-1",
              valueClasses[variant]
            )}
          >
            <SelectPrimitive.Value placeholder={placeholder} />
            <div className="flex items-center">
              {rightSection}
              <SelectPrimitive.Icon>
                <SvgChevronDownSmall
                  className={cn(
                    "h-4 w-4 stroke-text-03 transition-transform",
                    isOpen && "rotate-180"
                  )}
                />
              </SelectPrimitive.Icon>
            </div>
          </div>
        </SelectPrimitive.Trigger>
        <div
          ref={dropdownRef}
          role="listbox"
          className={cn(
            "w-full max-h-72 overflow-auto rounded-12 border border-border-01 bg-background-neutral-00 p-1",
            "transition-all duration-200",
            isOpen
              ? "opacity-100 scale-100 translate-y-0"
              : "opacity-0 scale-95 -translate-y-2 pointer-events-none"
          )}
          style={{
            top: "calc(100% + 4px)",
            left: 0,
          }}
        >
          <SelectPrimitive.Content>
            {options.map((option) => (
              <SelectPrimitive.Item
                key={option.value}
                value={option.value}
                disabled={option.disabled}
                className={cn(
                  "relative flex flex-col w-full cursor-default select-none rounded-08 p-1.5 group",
                  "text-text-04 outline-none",
                  "hover:bg-background-tint-02 data-[highlighted]:bg-background-tint-02",
                  "data-[state=checked]:bg-action-link-01 data-[state=checked]:text-action-link-05",
                  "data-[disabled]:pointer-events-none data-[disabled]:opacity-50"
                )}
                onSelect={() => setIsOpen(false)}
              >
                <SelectPrimitive.ItemText className="text-text-04 font-main-ui-action">
                  {option.label}
                </SelectPrimitive.ItemText>
                {option.description && (
                  <span className="text-sm text-text-03 font-secondary-body group-data-[state=checked]:text-text-00 mt-0.5">
                    {option.description}
                  </span>
                )}
              </SelectPrimitive.Item>
            ))}
          </SelectPrimitive.Content>
        </div>
      </SelectPrimitive.Root>
    </div>
  );
}
