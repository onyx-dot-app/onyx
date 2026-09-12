import React, { useEffect, forwardRef } from "react";
import { createPortal } from "react-dom";
import "@opal/components/inputs/selections/dropdown/styles.css";
import { cn } from "@opal/utils";
import { ShadowDiv } from "@opal/components/shadow-div/components";
import { OptionsList } from "./OptionsList";
import { SelectOption, SelectSection } from "../types";

interface SelectDropdownProps {
  isOpen: boolean;
  disabled: boolean;
  floatingStyles: React.CSSProperties;
  setFloatingRef: (node: HTMLDivElement | null) => void;
  fieldId: string;
  placeholder: string;
  sections: SelectSection[];
  /** The supplied set itself is empty (options={[]}), not merely filtered out. */
  emptySet?: boolean;
  value: string;
  selectedValues?: ReadonlySet<string>;
  markAllMatches?: boolean;
  highlightedIndex: number;
  onSelect: (option: SelectOption) => void;
  onMouseEnter: (index: number) => void;
  onMouseMove: () => void;
  /** Pointer left the listbox — clear the pointer-driven highlight. */
  onMouseLeave: () => void;
  isExactMatch: (option: SelectOption) => boolean;
  /** Current input value for creating new option */
  inputValue: string;
  /** Whether to show create option when no exact match */
  allowCreate: boolean;
  /** Whether to show create option (pre-computed by parent) */
  showCreateOption: boolean;
  /** Prefix shown before the typed value in the create option (e.g., "Use", "Add") */
  createPrefix?: string;
  /** Max height of the dropdown in CSS units. Defaults to "15rem". */
  dropdownMaxHeight?: string;
}

/**
 * Renders the dropdown menu in a portal
 * Handles scroll-into-view for highlighted options
 */
export const SelectDropdown = forwardRef<HTMLDivElement, SelectDropdownProps>(
  (
    {
      isOpen,
      disabled,
      floatingStyles,
      setFloatingRef,
      fieldId,
      placeholder,
      sections,
      emptySet,
      value,
      selectedValues,
      markAllMatches,
      highlightedIndex,
      onSelect,
      onMouseEnter,
      onMouseMove,
      onMouseLeave,
      isExactMatch,
      inputValue,
      allowCreate,
      showCreateOption,
      createPrefix,
      dropdownMaxHeight,
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
        tabIndex={-1}
        aria-label={placeholder}
        className="opal-select-dropdown"
        style={floatingStyles}
        onMouseLeave={onMouseLeave}
        onMouseDown={(e) => {
          // Clicks on padding, gaps, or dividers must not steal focus from
          // the combobox input (the listbox is tabIndex={-1} for AT only).
          e.preventDefault();
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
        <ShadowDiv
          shadowHeight="0.75rem"
          className={cn(
            "opal-select-dropdown-scroll",
            !dropdownMaxHeight && "max-h-60"
          )}
          style={{
            // Scroll independently of whatever sits behind the portal.
            overscrollBehavior: "contain",
            ...(dropdownMaxHeight ? { maxHeight: dropdownMaxHeight } : {}),
          }}
        >
          <OptionsList
            sections={sections}
            emptySet={emptySet}
            value={value}
            selectedValues={selectedValues}
            markAllMatches={markAllMatches}
            highlightedIndex={highlightedIndex}
            fieldId={fieldId}
            onSelect={onSelect}
            onMouseEnter={onMouseEnter}
            onMouseMove={onMouseMove}
            isExactMatch={isExactMatch}
            inputValue={inputValue}
            allowCreate={allowCreate}
            showCreateOption={showCreateOption}
            createPrefix={createPrefix}
          />
        </ShadowDiv>
      </div>,
      document.body
    );
  }
);

SelectDropdown.displayName = "SelectDropdown";
