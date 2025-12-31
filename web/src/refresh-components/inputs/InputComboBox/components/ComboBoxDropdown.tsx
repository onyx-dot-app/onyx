import React, { useEffect, forwardRef } from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/utils";
import { OptionsList } from "./OptionsList";
import { ComboBoxOption } from "../types";

interface ComboBoxDropdownProps {
  isOpen: boolean;
  disabled: boolean;
  floatingStyles: React.CSSProperties;
  setFloatingRef: (node: HTMLDivElement | null) => void;
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
  /** Current input value for creating new option */
  inputValue: string;
  /** Whether to show create option when no exact match */
  allowCreate: boolean;
  /** Whether to show create option (pre-computed by parent) */
  showCreateOption: boolean;
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
      floatingStyles,
      setFloatingRef,
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
      inputValue,
      allowCreate,
      showCreateOption,
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
            behavior: "instant",
          });
        }
      }
    }, [highlightedIndex, isOpen, ref]);

    if (!isOpen || disabled || typeof document === "undefined") {
      return null;
    }

    return createPortal(
      <div
        ref={(node) => {
          // Handle both the forwarded ref and the floating ref
          setFloatingRef(node);
          if (typeof ref === "function") {
            ref(node);
          } else if (ref) {
            ref.current = node;
          }
        }}
        id={`${fieldId}-listbox`}
        role="listbox"
        aria-label={placeholder}
        className={cn(
          "z-[10000] bg-background-neutral-00 border border-border-02 rounded-12 shadow-02 max-h-60 overflow-y-auto overflow-x-hidden p-1 pointer-events-auto touch-auto"
        )}
        style={{
          ...floatingStyles,
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
          inputValue={inputValue}
          allowCreate={allowCreate}
          showCreateOption={showCreateOption}
        />
      </div>,
      document.body
    );
  }
);

ComboBoxDropdown.displayName = "ComboBoxDropdown";
