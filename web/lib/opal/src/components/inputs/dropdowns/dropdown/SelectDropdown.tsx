import React, { useEffect, forwardRef } from "react";
import { createPortal } from "react-dom";
import "@opal/components/inputs/dropdowns/dropdown/styles.css";
import { cn } from "@opal/utils";
import { ShadowDiv } from "@opal/components/shadow-div/components";
import usePresence from "@opal/hooks/usePresence";
import { OptionsList } from "./OptionsList";
import type { SelectOption } from "../types";
import type { OptionGroup } from "../shared";

interface SelectDropdownProps {
  isOpen: boolean;
  disabled: boolean;
  floatingStyles: React.CSSProperties;
  setFloatingRef: (node: HTMLDivElement | null) => void;
  fieldId: string;
  placeholder: string;
  sections: OptionGroup[];
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
  /** Max height of the dropdown in CSS units. Defaults to "15rem". */
  dropdownMaxHeight?: string;
  /**
   * Whether the highlight is being driven by the keyboard. Only then does
   * the list scroll to keep the highlighted row in view; a pointer moving
   * over rows must never scroll the list under itself.
   */
  keyboardNav: boolean;
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
      dropdownMaxHeight,
      keyboardNav,
    },
    ref
  ) => {
    // The listbox stays mounted one exit animation longer than `isOpen`, so
    // it can animate out without living in the tree while closed.
    const presence = usePresence(isOpen);

    // Keyboard navigation keeps the highlighted row in view. Pointer
    // highlights never scroll: the list must not move under the mouse.
    useEffect(() => {
      if (
        isOpen &&
        keyboardNav &&
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
    }, [highlightedIndex, isOpen, keyboardNav, ref]);

    // Opening shows the selection: the (first) selected row is centred in
    // view, so a long list opens around the current value.
    useEffect(() => {
      if (!isOpen || !ref || typeof ref === "function" || !ref.current) {
        return;
      }
      const selectedElement = ref.current.querySelector(
        '[role="option"][aria-selected="true"]'
      );
      selectedElement?.scrollIntoView({
        block: "center",
        behavior: "instant",
      });
    }, [isOpen, ref]);

    if (!presence.mounted || disabled || typeof document === "undefined") {
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
        // Closed while exiting: invisible to AT and to the pointer.
        aria-hidden={presence.state === "closed" || undefined}
        data-state={presence.state}
        className="opal-select-dropdown"
        style={floatingStyles}
        onAnimationEnd={presence.onAnimationEnd}
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
          shadowHeight={3}
          // Fade the rows themselves at the scroll edges. A painted shadow
          // sat on top of the rows and read as a smudge on the light surface.
          variant="mask"
          // The rise-and-settle runs on this non-scrolling wrapper: a
          // transform on the scroller itself makes Chromium repaint it at
          // scroll offset 0 for a frame when compositing switches.
          containerClassName="opal-select-dropdown-content"
          className={cn(
            "opal-select-dropdown-scroll",
            !dropdownMaxHeight && "max-h-60"
          )}
          style={{
            // Scroll independently of whatever sits behind the portal.
            overscrollBehavior: "contain",
            maxHeight: dropdownMaxHeight || undefined,
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
          />
        </ShadowDiv>
      </div>,
      document.body
    );
  }
);

SelectDropdown.displayName = "SelectDropdown";
