"use client";

import React, { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { useBoundingBox } from "@/hooks/useBoundingBox";
import * as SelectPrimitive from "@radix-ui/react-select";
import { ChevronDown } from "lucide-react";

const triggerClasses = (
  active?: boolean,
  hovered?: boolean,
  isError?: boolean
) =>
  ({
    defaulted: [
      "border",
      isError && "!border-status-error-05",
      !isError && hovered && "border-border-02",
      !isError && active && "border-border-05",
    ],
    internal: [],
    disabled: ["bg-background-neutral-03"],
  }) as const;

const valueClasses = () =>
  ({
    defaulted: [
      "text-text-04 placeholder:!font-secondary-body placeholder:text-text-02",
    ],
    internal: [],
    disabled: ["text-text-02"],
  }) as const;

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
  active?: boolean;
  internal?: boolean;
  disabled?: boolean;
  isError?: boolean;

  // Select specific props
  value?: string;
  onValueChange?: (value: string) => void;
  options: InputSelectOption[];
  placeholder?: string;

  // Right section of the input, e.g. action button
  rightSection?: React.ReactNode;

  // Additional styling
  className?: string;

  // Radix select props
  name?: string;
  required?: boolean;
}

function InputSelectInner(
  {
    active,
    internal,
    disabled,
    isError,
    value,
    onValueChange,
    options,
    placeholder = "Select an option",
    rightSection,
    className,
    name,
    required,
    ...props
  }: InputSelectProps,
  ref: React.ForwardedRef<HTMLButtonElement>
) {
  const { ref: boundingBoxRef, inside: hovered } = useBoundingBox();
  const [localActive, setLocalActive] = useState(active);

  const state = internal ? "internal" : disabled ? "disabled" : "defaulted";

  useEffect(() => {
    // if disabled, set cursor to "not-allowed"
    if (disabled && hovered) {
      document.body.style.cursor = "not-allowed";
    } else if (!disabled && hovered) {
      document.body.style.cursor = "pointer";
    } else {
      document.body.style.cursor = "default";
    }
  }, [hovered, disabled]);

  return (
    <SelectPrimitive.Root
      value={value}
      onValueChange={onValueChange}
      disabled={disabled}
      name={name}
      required={required}
    >
      <div
        ref={boundingBoxRef}
        className={cn(
          "flex flex-row items-center justify-between w-full h-fit p-1.5 rounded-08 bg-background-neutral-00 relative",
          triggerClasses(localActive, hovered, isError)[state],
          className
        )}
      >
        <SelectPrimitive.Trigger
          ref={ref}
          className={cn(
            "w-full h-[1.5rem] bg-transparent p-0.5 focus:outline-none flex items-center justify-between",
            valueClasses()[state]
          )}
          onFocus={() => setLocalActive(true)}
          onBlur={() => setLocalActive(false)}
          {...props}
        >
          <SelectPrimitive.Value placeholder={placeholder} />
          <SelectPrimitive.Icon asChild>
            <ChevronDown className="h-4 w-4 opacity-50 ml-2 flex-shrink-0" />
          </SelectPrimitive.Icon>
        </SelectPrimitive.Trigger>
        {rightSection}
      </div>

      <SelectPrimitive.Portal>
        <SelectPrimitive.Content
          className={cn(
            "relative z-[2000] max-h-72 min-w-[8rem] overflow-hidden rounded-12 border border-border-01 bg-background-neutral-00 shadow-02",
            "data-[state=open]:animate-in data-[state=closed]:animate-out",
            "data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0",
            "data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95",
            "data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2",
            "data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2"
          )}
          position="popper"
          sideOffset={4}
          style={{ width: "var(--radix-select-trigger-width)" }}
        >
          <SelectPrimitive.ScrollUpButton className="flex cursor-default items-center justify-center py-1">
            <ChevronDown className="h-4 w-4 rotate-180" />
          </SelectPrimitive.ScrollUpButton>

          <SelectPrimitive.Viewport className="p-1">
            {options.map((option) => (
              <SelectPrimitive.Item
                key={option.value}
                value={option.value}
                disabled={option.disabled}
                className={cn(
                  "relative flex flex-col w-full cursor-default select-none rounded-08 p-1.5",
                  "text-text-04 outline-none",
                  "hover:bg-background-tint-02",
                  "data-[state=checked]:bg-action-link-01 data-[state=checked]:text-action-link-05",
                  "data-[disabled]:pointer-events-none data-[disabled]:opacity-50"
                )}
              >
                <SelectPrimitive.ItemText className="text-text-04 font-main-ui-action">
                  {option.label}
                </SelectPrimitive.ItemText>
                {option.description && (
                  <span className="text-sm text-text-03 font-secondary-body data-[state=checked]:text-text-00 mt-0.5">
                    {option.description}
                  </span>
                )}
              </SelectPrimitive.Item>
            ))}
          </SelectPrimitive.Viewport>

          <SelectPrimitive.ScrollDownButton className="flex cursor-default items-center justify-center py-1">
            <ChevronDown className="h-4 w-4" />
          </SelectPrimitive.ScrollDownButton>
        </SelectPrimitive.Content>
      </SelectPrimitive.Portal>
    </SelectPrimitive.Root>
  );
}

const InputSelect = React.forwardRef(InputSelectInner);
InputSelect.displayName = "InputSelect";

export default InputSelect;
