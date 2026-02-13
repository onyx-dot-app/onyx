"use client";

import React, {
  createContext,
  useContext,
  useEffect,
  useCallback,
  useRef,
  useMemo,
} from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import * as VisuallyHidden from "@radix-ui/react-visually-hidden";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import LineItem from "@/refresh-components/buttons/LineItem";
import Tag from "@/refresh-components/buttons/Tag";
import { Button } from "@opal/components";
import ScrollIndicatorDiv from "@/refresh-components/ScrollIndicatorDiv";
import Divider from "@/refresh-components/Divider";
import { Section } from "@/layouts/general-layouts";
import { SvgSearch, SvgX } from "@opal/icons";
import type {
  CommandMenuProps,
  CommandMenuContentProps,
  CommandMenuHeaderProps,
  CommandMenuListProps,
  CommandMenuFilterProps,
  CommandMenuItemProps,
  CommandMenuActionProps,
  CommandMenuFooterProps,
  CommandMenuFooterActionProps,
  CommandMenuContextValue,
} from "./types";

// =============================================================================
// Context
// =============================================================================

const CommandMenuContext = createContext<CommandMenuContextValue | null>(null);

function useCommandMenuContext() {
  const context = useContext(CommandMenuContext);
  if (!context) {
    throw new Error(
      "CommandMenu compound components must be used within CommandMenu"
    );
  }
  return context;
}

// =============================================================================
// CommandMenu Root
// =============================================================================

/**
 * Gets ordered items by querying DOM for data-command-item elements.
 * Safe to call in event handlers (after DOM is committed).
 */
function getOrderedItems(): string[] {
  const container = document.querySelector("[data-command-menu-list]");
  if (!container) return [];
  const elements = container.querySelectorAll("[data-command-item]");
  return Array.from(elements)
    .map((el) => el.getAttribute("data-command-item"))
    .filter((v): v is string => v !== null);
}

/**
 * CommandMenu Root Component
 *
 * Wrapper around Radix Dialog.Root for managing command menu state.
 * Centralizes all keyboard/selection logic - items only render and report mouse events.
 *
 * @example
 * ```tsx
 * <CommandMenu open={isOpen} onOpenChange={setIsOpen}>
 *   <CommandMenu.Content>
 *     <CommandMenu.Header placeholder="Search..." />
 *     <CommandMenu.List>
 *       <CommandMenu.Item value="1">Item 1</CommandMenu.Item>
 *     </CommandMenu.List>
 *     <CommandMenu.Footer />
 *   </CommandMenu.Content>
 * </CommandMenu>
 * ```
 */
function CommandMenuRoot({ open, onOpenChange, children }: CommandMenuProps) {
  const [highlightedValue, setHighlightedValue] = React.useState<string | null>(
    null
  );
  const [isKeyboardNav, setIsKeyboardNav] = React.useState(false);
  const [itemsRevision, setItemsRevision] = React.useState(0);

  // Centralized callback registry - items register their onSelect callback, type, and defaultHighlight
  const itemCallbacks = useRef<
    Map<
      string,
      {
        callback: () => void;
        type: "filter" | "item" | "action";
        defaultHighlight: boolean;
      }
    >
  >(new Map());

  // Track previous itemsRevision to detect when items actually change
  const prevItemsRevisionRef = useRef(itemsRevision);

  // Reset state when menu closes
  useEffect(() => {
    if (!open) {
      setHighlightedValue(null);
      setIsKeyboardNav(false);
      itemCallbacks.current.clear();
    }
  }, [open]);

  // Ensure valid highlight when menu is open and items change
  useEffect(() => {
    if (open) {
      const frame = requestAnimationFrame(() => {
        const items = getOrderedItems();
        const currentEntry = highlightedValue
          ? itemCallbacks.current.get(highlightedValue)
          : null;

        const itemsChanged = prevItemsRevisionRef.current !== itemsRevision;
        prevItemsRevisionRef.current = itemsRevision;

        // Re-evaluate if:
        // 1. No highlight set
        // 2. Current highlight is not in DOM
        // 3. Items changed AND current highlight has defaultHighlight=false
        const shouldReselect =
          !highlightedValue ||
          !items.includes(highlightedValue) ||
          (itemsChanged && currentEntry?.defaultHighlight === false);

        if (shouldReselect) {
          // Find first item eligible for default highlight
          const defaultItem = items.find((value) => {
            const entry = itemCallbacks.current.get(value);
            return entry?.defaultHighlight !== false;
          });
          // Use default item if found, otherwise fall back to first item
          const targetItem = defaultItem || items[0];
          setHighlightedValue(targetItem || null);
        }
      });
      return () => cancelAnimationFrame(frame);
    }
  }, [open, highlightedValue, itemsRevision]);

  // Registration functions (items call on mount)
  const registerItem = useCallback(
    (
      value: string,
      onSelect: () => void,
      type: "filter" | "item" | "action" = "item",
      defaultHighlight: boolean = true
    ) => {
      if (
        process.env.NODE_ENV === "development" &&
        itemCallbacks.current.has(value)
      ) {
        console.warn(
          `[CommandMenu] Duplicate value "${value}" registered. ` +
            `Values must be unique across all Filter, Item, and Action components.`
        );
      }
      itemCallbacks.current.set(value, {
        callback: onSelect,
        type,
        defaultHighlight,
      });
      setItemsRevision((r) => r + 1);
    },
    []
  );

  const unregisterItem = useCallback((value: string) => {
    itemCallbacks.current.delete(value);
    setItemsRevision((r) => r + 1);
  }, []);

  // Shared mouse handlers (items call on events)
  const onItemMouseEnter = useCallback(
    (value: string) => {
      if (!isKeyboardNav) {
        setHighlightedValue(value);
      }
    },
    [isKeyboardNav]
  );

  const onItemMouseMove = useCallback(
    (value: string) => {
      if (isKeyboardNav) {
        setIsKeyboardNav(false);
      }
      if (highlightedValue !== value) {
        setHighlightedValue(value);
      }
    },
    [isKeyboardNav, highlightedValue]
  );

  const onItemClick = useCallback(
    (value: string) => {
      const entry = itemCallbacks.current.get(value);
      entry?.callback();
      if (entry?.type !== "filter") {
        onOpenChange(false);
      }
    },
    [onOpenChange]
  );

  const onListMouseLeave = useCallback(() => {
    if (!isKeyboardNav) {
      setHighlightedValue(null);
    }
  }, [isKeyboardNav]);

  // Compute the type of the currently highlighted item
  const highlightedItemType = useMemo(() => {
    if (!highlightedValue) return null;
    return itemCallbacks.current.get(highlightedValue)?.type ?? null;
  }, [highlightedValue]);

  // Keyboard handler - centralized for all keys including Enter
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      switch (e.key) {
        case "ArrowDown": {
          e.preventDefault();
          setIsKeyboardNav(true);
          const items = getOrderedItems();
          if (items.length === 0) return;

          const currentIndex = highlightedValue
            ? items.indexOf(highlightedValue)
            : -1;
          const nextIndex =
            currentIndex < items.length - 1 ? currentIndex + 1 : 0;
          const nextItem = items[nextIndex];
          if (nextItem !== undefined) {
            setHighlightedValue(nextItem);
          }
          break;
        }
        case "ArrowUp": {
          e.preventDefault();
          setIsKeyboardNav(true);
          const items = getOrderedItems();
          if (items.length === 0) return;

          const currentIndex = highlightedValue
            ? items.indexOf(highlightedValue)
            : 0;
          const prevIndex =
            currentIndex > 0 ? currentIndex - 1 : items.length - 1;
          const prevItem = items[prevIndex];
          if (prevItem !== undefined) {
            setHighlightedValue(prevItem);
          }
          break;
        }
        case "Enter": {
          e.preventDefault();
          e.stopPropagation();
          if (highlightedValue) {
            const entry = itemCallbacks.current.get(highlightedValue);
            entry?.callback();
            if (entry?.type !== "filter") {
              onOpenChange(false);
            }
          }
          break;
        }
        case "Escape": {
          e.preventDefault();
          onOpenChange(false);
          break;
        }
      }
    },
    [highlightedValue, onOpenChange]
  );

  // Scroll highlighted item into view on keyboard nav
  // Uses manual scroll calculation instead of scrollIntoView to only scroll
  // the list container, not the modal or other ancestors
  useEffect(() => {
    if (isKeyboardNav && highlightedValue) {
      const container = document.querySelector("[data-command-menu-list]");
      // Use safe attribute matching instead of direct selector interpolation
      // to prevent CSS selector injection
      const el = Array.from(
        container?.querySelectorAll("[data-command-item]") ?? []
      ).find((e) => e.getAttribute("data-command-item") === highlightedValue);

      if (container && el instanceof HTMLElement) {
        const containerRect = container.getBoundingClientRect();
        const elRect = el.getBoundingClientRect();

        const scrollMargin = 60;
        if (elRect.top < containerRect.top + scrollMargin) {
          container.scrollTop -= containerRect.top + scrollMargin - elRect.top;
        } else if (elRect.bottom > containerRect.bottom) {
          container.scrollTop += elRect.bottom - containerRect.bottom;
        }
      }
    }
  }, [highlightedValue, isKeyboardNav]);

  const contextValue = useMemo<CommandMenuContextValue>(
    () => ({
      highlightedValue,
      highlightedItemType,
      isKeyboardNav,
      registerItem,
      unregisterItem,
      onItemMouseEnter,
      onItemMouseMove,
      onItemClick,
      onListMouseLeave,
      handleKeyDown,
    }),
    [
      highlightedValue,
      highlightedItemType,
      isKeyboardNav,
      registerItem,
      unregisterItem,
      onItemMouseEnter,
      onItemMouseMove,
      onItemClick,
      onListMouseLeave,
      handleKeyDown,
    ]
  );

  return (
    <CommandMenuContext.Provider value={contextValue}>
      <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
        {children}
      </DialogPrimitive.Root>
    </CommandMenuContext.Provider>
  );
}

// =============================================================================
// CommandMenu Content
// =============================================================================

/**
 * CommandMenu Content Component
 *
 * Modal container with overlay, sizing, and animations.
 * Keyboard handling is centralized in Root and accessed via context.
 */
const CommandMenuContent = React.forwardRef<
  React.ComponentRef<typeof DialogPrimitive.Content>,
  CommandMenuContentProps
>(({ children }, ref) => {
  const { handleKeyDown } = useCommandMenuContext();

  return (
    <DialogPrimitive.Portal>
      {/* Overlay - hidden from assistive technology */}
      <DialogPrimitive.Overlay
        aria-hidden="true"
        className={cn(
          "fixed inset-0 z-modal-overlay bg-mask-03 backdrop-blur-03 pointer-events-none",
          "data-[state=open]:animate-in data-[state=closed]:animate-out",
          "data-[state=open]:fade-in-0 data-[state=closed]:fade-out-0"
        )}
      />
      {/* Content */}
      <DialogPrimitive.Content
        ref={ref}
        onKeyDown={handleKeyDown}
        className={cn(
          "fixed inset-x-0 top-[72px] mx-auto",
          "z-modal",
          "bg-background-tint-00 border rounded-16 shadow-2xl outline-none",
          "flex flex-col overflow-hidden",
          "max-w-[calc(100dvw-2rem)] max-h-[calc(100dvh-144px)]",
          "data-[state=open]:animate-in data-[state=closed]:animate-out",
          "data-[state=open]:fade-in-0 data-[state=closed]:fade-out-0",
          "data-[state=open]:slide-in-from-bottom data-[state=open]:slide-in-from-left-0",
          "data-[state=closed]:slide-out-to-bottom data-[state=closed]:slide-out-to-left-0",
          "duration-200",
          "w-[32rem]",
          "min-h-[15rem]"
        )}
      >
        <VisuallyHidden.Root asChild>
          <DialogPrimitive.Title>Command Menu</DialogPrimitive.Title>
        </VisuallyHidden.Root>
        {children}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
});
CommandMenuContent.displayName = "CommandMenuContent";

// =============================================================================
// CommandMenu Header
// =============================================================================

/**
 * CommandMenu Header Component
 *
 * Contains filter tags and search input.
 * Arrow keys preventDefault at input level (to stop cursor movement) then bubble to Content.
 */
function CommandMenuHeader({
  placeholder = "Search...",
  filters = [],
  value = "",
  onValueChange,
  onFilterRemove,
  onClose,
  onEmptyBackspace,
}: CommandMenuHeaderProps) {
  // Prevent default for arrow/enter keys so they don't move cursor or submit forms
  // The actual handling happens in Root's centralized handler via event bubbling
  const handleInputKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "Enter") {
        e.preventDefault();
      }
      // Handle backspace on empty input for navigation
      if (e.key === "Backspace" && !value) {
        onEmptyBackspace?.();
      }
    },
    [value, onEmptyBackspace]
  );

  return (
    <div className="flex-shrink-0">
      {/* Top row: Search icon, filters, close button */}
      <div className="px-3 pt-3 flex flex-row justify-between items-center">
        <Section
          flexDirection="row"
          justifyContent="start"
          gap={0.5}
          width="fit"
        >
          {/* Standalone search icon */}
          <SvgSearch className="w-6 h-6 stroke-text-04" />
          {filters.map((filter) => (
            <Tag
              variant="editable"
              key={filter.id}
              label={filter.label}
              icon={filter.icon}
              onRemove={
                onFilterRemove ? () => onFilterRemove(filter.id) : undefined
              }
            />
          ))}
        </Section>
        {onClose && (
          <DialogPrimitive.Close asChild>
            <Button
              icon={SvgX}
              prominence="tertiary"
              size="sm"
              onClick={onClose}
              aria-label="Close menu"
            />
          </DialogPrimitive.Close>
        )}
      </div>
      {/* Search input - arrow/enter keys bubble up to Content for centralized handling */}
      <div className="px-2 pb-2 pt-0.5">
        <InputTypeIn
          placeholder={placeholder}
          value={value}
          onChange={(e) => onValueChange?.(e.target.value)}
          onKeyDown={handleInputKeyDown}
          autoFocus
          className="w-full !bg-transparent !border-transparent [&:is(:hover,:active,:focus,:focus-within)]:!bg-background-neutral-00 [&:is(:hover)]:!border-border-01 [&:is(:focus,:focus-within)]:!shadow-none"
          showClearButton={false}
        />
      </div>
    </div>
  );
}

// =============================================================================
// CommandMenu List
// =============================================================================

/**
 * CommandMenu List Component
 *
 * Scrollable container for menu items with scroll shadow indicators.
 * Uses ScrollIndicatorDiv for automatic scroll shadows.
 */
function CommandMenuList({ children, emptyMessage }: CommandMenuListProps) {
  const { isKeyboardNav, onListMouseLeave } = useCommandMenuContext();
  const childCount = React.Children.count(children);

  if (childCount === 0 && emptyMessage) {
    return (
      <div
        className="bg-background-tint-01 p-4"
        role="status"
        aria-live="polite"
      >
        <Text secondaryBody text03>
          {emptyMessage}
        </Text>
      </div>
    );
  }

  return (
    <ScrollIndicatorDiv
      role="listbox"
      aria-label="Command menu options"
      className="p-1 gap-1 max-h-[60vh] bg-background-tint-01"
      backgroundColor="var(--background-tint-01)"
      data-command-menu-list
      data-keyboard-nav={isKeyboardNav ? "true" : undefined}
      variant="shadow"
      onMouseLeave={onListMouseLeave}
    >
      {children}
    </ScrollIndicatorDiv>
  );
}

// =============================================================================
// CommandMenu Filter
// =============================================================================

/**
 * CommandMenu Filter Component
 *
 * When `isApplied` is true, renders as a non-interactive group label.
 * Otherwise, renders as a selectable filter with a chevron indicator.
 * Dumb component - registers callback on mount, renders based on context state.
 */
function CommandMenuFilter({
  value,
  children,
  icon,
  isApplied,
  onSelect,
}: CommandMenuFilterProps) {
  const {
    highlightedValue,
    registerItem,
    unregisterItem,
    onItemMouseEnter,
    onItemMouseMove,
    onItemClick,
  } = useCommandMenuContext();

  // Register callback on mount - NO keyboard listener needed
  useEffect(() => {
    if (!isApplied && onSelect) {
      registerItem(value, () => onSelect(), "filter");
      return () => unregisterItem(value);
    }
  }, [value, isApplied, onSelect, registerItem, unregisterItem]);

  // When filter is applied, show as group label (non-interactive)
  if (isApplied) {
    return (
      <Divider
        showTitle
        text={children as string}
        icon={icon}
        dividerLine={false}
      />
    );
  }

  const isHighlighted = value === highlightedValue;

  // Selectable filter - uses LineItem, delegates all events to context
  return (
    <div data-command-item={value} role="option" aria-selected={isHighlighted}>
      <Divider
        showTitle
        text={children as string}
        icon={icon}
        foldable
        isHighlighted={isHighlighted}
        onClick={() => onItemClick(value)}
        onMouseEnter={() => onItemMouseEnter(value)}
        onMouseMove={() => onItemMouseMove(value)}
        dividerLine={false}
      />
    </div>
  );
}

// =============================================================================
// CommandMenu Item
// =============================================================================

/**
 * CommandMenu Item Component
 *
 * Dumb component - registers callback on mount, renders based on context state.
 * Use rightContent for timestamps, badges, etc.
 */
function CommandMenuItem({
  value,
  icon,
  rightContent,
  onSelect,
  children,
}: CommandMenuItemProps) {
  const {
    highlightedValue,
    registerItem,
    unregisterItem,
    onItemMouseEnter,
    onItemMouseMove,
    onItemClick,
  } = useCommandMenuContext();

  // Register callback on mount - NO keyboard listener needed
  useEffect(() => {
    registerItem(value, () => onSelect?.(value));
    return () => unregisterItem(value);
  }, [value, onSelect, registerItem, unregisterItem]);

  const isHighlighted = value === highlightedValue;

  // Resolve rightContent - supports both static ReactNode and render function
  const resolvedRightContent =
    typeof rightContent === "function"
      ? rightContent({ isHighlighted })
      : rightContent;

  return (
    <div data-command-item={value} role="option" aria-selected={isHighlighted}>
      <LineItem
        muted
        icon={icon}
        rightChildren={resolvedRightContent}
        emphasized={isHighlighted}
        selected={isHighlighted}
        onClick={() => onItemClick(value)}
        onMouseEnter={() => onItemMouseEnter(value)}
        onMouseMove={() => onItemMouseMove(value)}
      >
        {children}
      </LineItem>
    </div>
  );
}

// =============================================================================
// CommandMenu Action
// =============================================================================

/**
 * CommandMenu Action Component
 *
 * Dumb component - registers callback on mount, renders based on context state.
 * Uses LineItem with action variant for visual distinction.
 */
function CommandMenuAction({
  value,
  icon,
  shortcut,
  onSelect,
  children,
  defaultHighlight = true,
}: CommandMenuActionProps) {
  const {
    highlightedValue,
    registerItem,
    unregisterItem,
    onItemMouseEnter,
    onItemMouseMove,
    onItemClick,
  } = useCommandMenuContext();

  // Register callback on mount - NO keyboard listener needed
  useEffect(() => {
    registerItem(value, () => onSelect?.(value), "action", defaultHighlight);
    return () => unregisterItem(value);
  }, [value, onSelect, defaultHighlight, registerItem, unregisterItem]);

  const isHighlighted = value === highlightedValue;

  return (
    <div data-command-item={value} role="option" aria-selected={isHighlighted}>
      <LineItem
        action
        icon={icon}
        rightChildren={
          shortcut ? (
            <Text figureKeystroke text02>
              {shortcut}
            </Text>
          ) : undefined
        }
        emphasized={isHighlighted}
        selected={isHighlighted}
        onClick={() => onItemClick(value)}
        onMouseEnter={() => onItemMouseEnter(value)}
        onMouseMove={() => onItemMouseMove(value)}
      >
        {children}
      </LineItem>
    </div>
  );
}

// =============================================================================
// CommandMenu Footer
// =============================================================================

/**
 * CommandMenu Footer Component
 *
 * Footer section with keyboard hint actions.
 */
function CommandMenuFooter({ leftActions }: CommandMenuFooterProps) {
  return (
    <div className="flex-shrink-0">
      <Section
        flexDirection="row"
        justifyContent="start"
        gap={1}
        padding={0.75}
      >
        {leftActions}
      </Section>
    </div>
  );
}

// =============================================================================
// CommandMenu Footer Action
// =============================================================================

/**
 * CommandMenu Footer Action Component
 *
 * Display-only visual hint showing a keyboard shortcut.
 */
function CommandMenuFooterAction({
  icon: Icon,
  label,
}: CommandMenuFooterActionProps) {
  return (
    <div className="flex items-center gap-1" aria-label={label}>
      <Icon
        className="w-[0.875rem] h-[0.875rem] stroke-text-02"
        aria-hidden="true"
      />
      <Text mainUiBody text03>
        {label}
      </Text>
    </div>
  );
}

// =============================================================================
// Export Compound Component
// =============================================================================

export { useCommandMenuContext };

export default Object.assign(CommandMenuRoot, {
  Content: CommandMenuContent,
  Header: CommandMenuHeader,
  List: CommandMenuList,
  Filter: CommandMenuFilter,
  Item: CommandMenuItem,
  Action: CommandMenuAction,
  Footer: CommandMenuFooter,
  FooterAction: CommandMenuFooterAction,
});
