"use client";

import React, {
  useState,
  useRef,
  useEffect,
  createContext,
  useContext,
} from "react";
import { cn } from "@/lib/utils";
import SvgChevronDownSmall from "@/icons/chevron-down-small";
import { useClickOutside } from "@/lib/hooks";
import LineItem, { LineItemProps } from "@/refresh-components/buttons/LineItem";

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
  ...props
}: InputSelectLineItemProps) {
  const { selectedValue, onSelect, isOpen } = useInputSelectContext();
  const isSelected = selectedValue === value;

  if (!isOpen) return null;

  return (
    <LineItem
      {...props}
      heavyForced={isSelected}
      description={description}
      onClick={() => onSelect(value)}
    >
      {children}
    </LineItem>
  );
}

// Main select component
export interface InputSelectProps {
  value?: string;
  onValueChange?: (value: string) => void;
  placeholder?: string;
  children: React.ReactElement<InputSelectLineItemProps>[];
  className?: string;
  disabled?: boolean;
}

export default function InputSelect({
  value,
  onValueChange,
  placeholder = "Select an option",
  children,
  className,
  disabled,
}: InputSelectProps) {
  const [isOpen, setIsOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useClickOutside(() => setIsOpen(false), [triggerRef, dropdownRef], isOpen);

  const handleSelect = (newValue: string) => {
    onValueChange?.(newValue);
    setIsOpen(false);
  };

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
              <span className="text-text-02">{placeholder}</span>
            )}
            <SvgChevronDownSmall
              className={cn(
                "h-4 w-4 stroke-text-03 transition-transform",
                isOpen && "rotate-180"
              )}
            />
          </div>
        </button>

        {isOpen && (
          <div
            ref={dropdownRef}
            className={cn(
              "absolute z-[2000] w-full mt-1 max-h-72 overflow-auto rounded-12 border border-border-01 bg-background-neutral-00 p-1",
              "animate-in fade-in-0 zoom-in-95 slide-in-from-top-2"
            )}
          >
            {children}
          </div>
        )}
      </div>
    </InputSelectContext.Provider>
  );
}
