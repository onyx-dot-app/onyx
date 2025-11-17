"use client";

import React, { useState, useRef, createContext, useContext } from "react";
import { cn } from "@/lib/utils";
import SvgChevronDownSmall from "@/icons/chevron-down-small";
import { useClickOutside } from "@/lib/hooks";
import LineItem, { LineItemProps } from "@/refresh-components/buttons/LineItem";
import { useEscape } from "@/hooks/useKeyPress";
import Text from "@/refresh-components/texts/Text";

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

// Main select component
export interface InputSelectProps {
  value?: string;
  onValueChange?: (value: string) => void;
  defaultValue?: string;
  placeholder?: React.ReactNode;
  children: React.ReactElement<InputSelectLineItemProps>[];
  className?: string;
  disabled?: boolean;
}

export default function InputSelect({
  value: controlledValue,
  onValueChange,
  defaultValue,
  placeholder,
  children,
  className,
  disabled,
}: InputSelectProps) {
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
            "flex w-full items-center justify-between p-1.5 rounded-08 bg-background-neutral-00 border border-border-01",
            "hover:border-border-02 active:border-border-05",
            "disabled:cursor-not-allowed disabled:bg-background-neutral-03",
            "focus:outline-none",
            className
          )}
        >
          <div className="flex flex-row items-center justify-between w-full p-0.5 gap-1">
            {selectedChild ? (
              <div className="flex flex-row items-center gap-2 flex-1">
                {selectedChild.props.icon && (
                  <selectedChild.props.icon className="h-4 w-4 stroke-text-03" />
                )}
                <span className="text-text-04 font-main-ui-action text-left">
                  {selectedChild.props.children}
                </span>
              </div>
            ) : (
              placeholder ?? <Text text03>Select an option</Text>
            )}

            <SvgChevronDownSmall
              className={cn(
                "h-4 w-4 stroke-text-03 transition-transform",
                isOpen && "rotate-180"
              )}
            />
          </div>
        </button>

        <div
          ref={dropdownRef}
          className={cn(
            "absolute z-[2000] w-full mt-1 max-h-72 overflow-auto rounded-12 border border-border-01 bg-background-neutral-00 p-1",
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
