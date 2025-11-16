"use client";

import React from "react";
import { cn } from "@/lib/utils";
import * as SelectPrimitive from "@radix-ui/react-select";
import SvgChevronDownSmall from "@/icons/chevron-down-small";
import SvgChevronUpSmall from "@/icons/chevron-up-small";

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

function InputSelectInner(
  {
    internal,
    error,
    disabled,

    value,
    onValueChange,
    options,
    placeholder = "Select an option",
    rightSection,
    className,
    ...props
  }: InputSelectProps,
  ref: React.ForwardedRef<HTMLButtonElement>
) {
  const variant = internal ? "internal" : disabled ? "disabled" : "main";

  return (
    <SelectPrimitive.Root
      value={value}
      onValueChange={onValueChange}
      disabled={disabled}
    >
      <SelectPrimitive.Trigger
        ref={ref}
        className={cn(
          "group/InputSelect flex-1 flex w-full items-center justify-between p-1.5 rounded-08 bg-background-neutral-00 hover:cursor-pointer disabled:cursor-not-allowed",
          triggerClasses[variant],
          className
        )}
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
            {rightSection && (
              <div
                className="flex items-center"
                onPointerDown={(e) => {
                  e.stopPropagation();
                }}
                onClick={(e) => {
                  e.stopPropagation();
                }}
              >
                {rightSection}
              </div>
            )}
            <SelectPrimitive.Icon>
              <SvgChevronDownSmall className="h-4 w-4 stroke-text-03 transition-transform group-data-[state=open]/InputSelect:-rotate-180" />
            </SelectPrimitive.Icon>
          </div>
        </div>
      </SelectPrimitive.Trigger>

      <SelectPrimitive.Content
        className={cn(
          "max-h-72 min-w-[8rem] w-[var(--radix-select-trigger-width)] overflow-hidden rounded-12 bg-background-neutral-00 border border-red-500",
          "data-[state=open]:animate-in data-[state=closed]:animate-out",
          "data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0",
          "data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95",
          "data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2",
          "data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2"
        )}
        position="popper"
        sideOffset={4}
      >
        {/*<SelectPrimitive.ScrollUpButton className="flex cursor-default items-center justify-center py-1">
          <SvgChevronUpSmall className="h-4 w-4 stroke-text-03" />
        </SelectPrimitive.ScrollUpButton>

        <SelectPrimitive.Viewport className="p-1">
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
        </SelectPrimitive.Viewport>

        <SelectPrimitive.ScrollDownButton className="flex cursor-default items-center justify-center py-1">
          <SvgChevronDownSmall className="h-4 w-4 stroke-text-03" />
        </SelectPrimitive.ScrollDownButton>*/}
      </SelectPrimitive.Content>
    </SelectPrimitive.Root>
  );
}

const InputSelect = React.forwardRef(InputSelectInner);
InputSelect.displayName = "InputSelect";

export default InputSelect;
