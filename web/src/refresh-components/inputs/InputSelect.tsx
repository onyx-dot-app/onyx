"use client";

import React, { useState, useRef, createContext, useContext } from "react";
import { cn } from "@/lib/utils";
import SvgChevronDownSmall from "@/icons/chevron-down-small";
import { useClickOutside } from "@/lib/hooks";
import LineItem, { LineItemProps } from "@/refresh-components/buttons/LineItem";
import { useEscape } from "@/hooks/useKeyPress";
import Text from "@/refresh-components/texts/Text";

// Style maps for different states
const triggerClasses = {
  main: [
    "bg-background-neutral-00",
    "border",
    "hover:border-border-02",
    "active:border-border-05",
    "cursor-pointer",
  ],
  error: ["border", "border-status-error-05", "bg-background-neutral-00"],
  disabled: [
    "bg-background-neutral-03",
    "border-border-01",
    "cursor-not-allowed",
  ],
} as const;

const textClasses = {
  main: ["text-text-04"],
  error: ["text-text-04"],
  disabled: ["text-text-01"],
} as const;

const iconClasses = {
  main: ["stroke-text-03"],
  error: ["stroke-text-03"],
  disabled: ["stroke-text-01"],
} as const;

// Context to share select state between parent and children
interface InputSelectContextValue {
  selectedValue: string | undefined;
  onSelect: (value: string) => void;
  isOpen: boolean;
}

const InputSelectContext = createContext<InputSelectContextValue | null>(null);

function useInputSelectContext() {
  const context = useContext(InputSelectContext);
  if (!context) {
    throw new Error("InputSelectLineItem must be used within InputSelect");
  }
  return context;
}

// LineItem wrapper for select options
export interface InputSelectLineItemProps
  extends Omit<LineItemProps, "heavyForced"> {
  value: string;
}

export function InputSelectLineItem({
  value,
  children,
  description,
  onClick,
  ...props
}: InputSelectLineItemProps) {
  const { selectedValue, onSelect } = useInputSelectContext();
  const isSelected = selectedValue === value;

  const handleMouseDown = (event: React.MouseEvent<HTMLButtonElement>) => {
    onSelect(value);
    onClick?.(event);
  };

  return (
    <LineItem
      {...props}
      heavyForced={isSelected}
      description={description}
      onClick={handleMouseDown}
    >
      {children}
    </LineItem>
  );
}

// Display component for selected child in trigger
interface SelectedLineItemProps {
  variant: keyof typeof textClasses;
  props?: InputSelectLineItemProps;
  placeholder?: React.ReactNode;
}

function SelectedLineItem({
  variant,
  props,
  placeholder,
}: SelectedLineItemProps) {
  if (!props) return placeholder ?? <Text text03>Select an option</Text>;

  return (
    <div className="flex flex-row items-center gap-2 flex-1">
      {props.icon && (
        <props.icon
          className={cn("h-4 w-4 stroke-text-03", iconClasses[variant])}
        />
      )}
      <Text className={cn(textClasses[variant])}>{props.children}</Text>
    </div>
  );
}

// Main select component
export interface InputSelectProps {
  disabled?: boolean;
  error?: boolean;

  value?: string;
  onValueChange?: (value: string) => void;
  defaultValue?: string;
  placeholder?: React.ReactNode;
  className?: string;
  rightSection?: React.ReactNode;
  children: React.ReactElement<InputSelectLineItemProps>[];
}

export default function InputSelect({
  disabled,
  error,

  value: controlledValue,
  onValueChange,
  defaultValue,
  placeholder,
  className,
  rightSection,
  children,
}: InputSelectProps) {
  const variant = disabled ? "disabled" : error ? "error" : "main";

  const [isOpen, setIsOpen] = useState(false);
  const [internalValue, setInternalValue] = useState<string | undefined>(
    defaultValue
  );
  const triggerRef = useRef<HTMLButtonElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  useClickOutside(() => setIsOpen(false), [triggerRef, dropdownRef], isOpen);
  useEscape(() => setIsOpen(false), isOpen);

  // Use controlled value if provided, otherwise use internal value
  const isControlled = controlledValue !== undefined;
  const value = isControlled ? controlledValue : internalValue;

  function handleSelect(newValue: string) {
    // Update internal state if uncontrolled
    if (!isControlled) {
      setInternalValue(newValue);
    }
    // Always call the callback if provided
    onValueChange?.(newValue);
    setIsOpen(false);
  }

  // Find the selected child to display in trigger
  const selectedChild = React.Children.toArray(children).find((child) => {
    if (React.isValidElement<InputSelectLineItemProps>(child)) {
      return child.props.value === value;
    }
    return false;
  }) as React.ReactElement<InputSelectLineItemProps> | undefined;

  const contextValue: InputSelectContextValue = {
    selectedValue: value,
    onSelect: handleSelect,
    isOpen,
  };

  return (
    <InputSelectContext.Provider value={contextValue}>
      <div className="relative w-full">
        <button
          ref={triggerRef}
          type="button"
          disabled={disabled}
          onClick={() => !disabled && setIsOpen(!isOpen)}
          className={cn(
            "flex w-full items-center justify-between p-1.5 rounded-08 border",
            "focus:outline-none",
            triggerClasses[variant],
            className
          )}
        >
          <div className="flex flex-row items-center justify-between w-full p-0.5 gap-1">
            <SelectedLineItem
              variant={variant}
              props={selectedChild?.props}
              placeholder={placeholder}
            />

            <div className="flex flex-row items-center">
              {rightSection}

              <SvgChevronDownSmall
                className={cn(
                  "h-4 w-4 transition-transform",
                  iconClasses[variant],
                  isOpen && "-rotate-180"
                )}
              />
            </div>
          </div>
        </button>

        <div
          ref={dropdownRef}
          className={cn(
            "absolute z-[2000] w-full mt-1 max-h-72 overflow-auto rounded-12 border bg-background-neutral-00 p-1",
            "transition-all duration-200",
            isOpen
              ? "opacity-100 scale-100 translate-y-0"
              : "opacity-0 scale-95 -translate-y-2 pointer-events-none"
          )}
        >
          {children}
        </div>
      </div>
    </InputSelectContext.Provider>
  );
}
