import React, { useEffect, forwardRef } from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/utils";
import { OptionsList } from "./OptionsList";
import { ComboBoxOption } from "../types";
import { DropdownPosition } from "@/hooks/useDropdownPosition";

interface ComboBoxDropdownProps {
  isOpen: boolean;
  disabled: boolean;
  dropdownPosition: DropdownPosition | null;
  fieldId: string;
  placeholder: string;
  matchedOptions: ComboBoxOption[];
  unmatchedOptions: ComboBoxOption[];
  hasSearchTerm: boolean;
  separatorLabel: string;
  value: string;
  highlightedIndex: number;
  onSelect: (option: ComboBoxOption) => void;
  onMouseEnter: (index: number) => void;
  onMouseMove: () => void;
  isExactMatch: (option: ComboBoxOption) => boolean;
}

/**
 * Renders the dropdown menu in a portal
 * Handles scroll-into-view for highlighted options
 */
export const ComboBoxDropdown = forwardRef<
  HTMLDivElement,
  ComboBoxDropdownProps
>(
  (
    {
      isOpen,
      disabled,
      dropdownPosition,
      fieldId,
      placeholder,
      matchedOptions,
      unmatchedOptions,
      hasSearchTerm,
      separatorLabel,
      value,
      highlightedIndex,
      onSelect,
      onMouseEnter,
      onMouseMove,
      isExactMatch,
    },
    ref
  ) => {
    // Scroll highlighted option into view
    useEffect(() => {
      if (
        isOpen &&
        ref &&
        typeof ref !== "function" &&
        ref.current &&
        highlightedIndex >= 0
      ) {
        const highlightedElement = ref.current.querySelector(
          `[data-index="${highlightedIndex}"]`
        );
        if (highlightedElement) {
          highlightedElement.scrollIntoView({
            block: "nearest",
            behavior: "smooth",
          });
        }
      }
    }, [highlightedIndex, isOpen, ref]);

    if (
      !isOpen ||
      disabled ||
      !dropdownPosition ||
      typeof document === "undefined"
    ) {
      return null;
    }

    return createPortal(
      <div
        ref={ref}
        id={`${fieldId}-listbox`}
        role="listbox"
        aria-label={placeholder}
        className={cn(
          "fixed z-[10000] bg-background-neutral-00 border border-border-02 rounded-12 shadow-02 max-h-60 overflow-y-auto overflow-x-hidden p-1 pointer-events-auto touch-auto"
        )}
        style={{
          top: `${dropdownPosition.top}px`,
          left: `${dropdownPosition.left}px`,
          ...(dropdownPosition.width && {
            width: `${dropdownPosition.width}px`,
          }),
          // Ensure the dropdown can scroll independently
          overscrollBehavior: "contain",
        }}
        onWheel={(e) => {
          // Prevent event from bubbling to prevent any parent scroll blocking
          e.stopPropagation();
        }}
        onTouchMove={(e) => {
          // Prevent event from bubbling for touch devices
          e.stopPropagation();
        }}
      >
        <OptionsList
          matchedOptions={matchedOptions}
          unmatchedOptions={unmatchedOptions}
          hasSearchTerm={hasSearchTerm}
          separatorLabel={separatorLabel}
          value={value}
          highlightedIndex={highlightedIndex}
          fieldId={fieldId}
          onSelect={onSelect}
          onMouseEnter={onMouseEnter}
          onMouseMove={onMouseMove}
          isExactMatch={isExactMatch}
        />
      </div>,
      document.body
    );
  }
);

ComboBoxDropdown.displayName = "ComboBoxDropdown";
