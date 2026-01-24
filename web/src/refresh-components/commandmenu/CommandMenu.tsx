"use client";

import React, {
  createContext,
  useContext,
  useEffect,
  useCallback,
  useRef,
} from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import LineItem from "@/refresh-components/buttons/LineItem";
import EditableTag from "@/refresh-components/buttons/EditableTag";
import IconButton from "@/refresh-components/buttons/IconButton";
import ShadowDiv from "@/refresh-components/ShadowDiv";
import Separator from "@/refresh-components/Separator";
import { Section } from "@/layouts/general-layouts";
import { SvgChevronRight, SvgSearch, SvgX } from "@opal/icons";
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

  // Centralized callback registry - items register their onSelect callback
  const itemCallbacks = useRef<Map<string, () => void>>(new Map());

  // Reset state when menu closes
  useEffect(() => {
    if (!open) {
      setHighlightedValue(null);
      setIsKeyboardNav(false);
      itemCallbacks.current.clear();
    }
  }, [open]);

  // Registration functions (items call on mount)
  const registerItem = useCallback((value: string, onSelect: () => void) => {
    itemCallbacks.current.set(value, onSelect);
  }, []);

  const unregisterItem = useCallback((value: string) => {
    itemCallbacks.current.delete(value);
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
      const callback = itemCallbacks.current.get(value);
      callback?.();
      onOpenChange(false);
    },
    [onOpenChange]
  );

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
          if (highlightedValue) {
            const callback = itemCallbacks.current.get(highlightedValue);
            callback?.();
            onOpenChange(false);
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
  useEffect(() => {
    if (isKeyboardNav && highlightedValue) {
      const el = document.querySelector(
        `[data-command-item="${highlightedValue}"]`
      );
      el?.scrollIntoView({ block: "nearest" });
    }
  }, [highlightedValue, isKeyboardNav]);

  const contextValue: CommandMenuContextValue = {
    highlightedValue,
    isKeyboardNav,
    registerItem,
    unregisterItem,
    onItemMouseEnter,
    onItemMouseMove,
    onItemClick,
    handleKeyDown,
  };

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
      {/* Overlay */}
      <DialogPrimitive.Overlay
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
          "fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2",
          "z-modal",
          "bg-background-tint-00 border rounded-16 shadow-2xl",
          "flex flex-col overflow-hidden",
          "data-[state=open]:animate-in data-[state=closed]:animate-out",
          "data-[state=open]:fade-in-0 data-[state=closed]:fade-out-0",
          "data-[state=open]:zoom-in-95 data-[state=closed]:zoom-out-95",
          "data-[state=open]:slide-in-from-top-1/2 data-[state=closed]:slide-out-to-top-1/2",
          "duration-200",
          "w-[32rem]",
          "max-h-[30rem]"
        )}
      >
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
}: CommandMenuHeaderProps) {
  // Prevent default for arrow/enter keys so they don't move cursor or submit forms
  // The actual handling happens in Root's centralized handler via event bubbling
  const handleInputKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "Enter") {
        e.preventDefault();
      }
    },
    []
  );

  return (
    <Section padding={1} gap={0.5} alignItems="start">
      {/* Top row: Search icon, filters, close button */}
      <Section flexDirection="row" justifyContent="between" gap={0.5}>
        <Section
          flexDirection="row"
          justifyContent="start"
          gap={0.5}
          width="fit"
        >
          {/* Standalone search icon */}
          <SvgSearch className="w-6 h-6 stroke-text-01" />
          {filters.map((filter) => (
            <EditableTag
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
            <IconButton icon={SvgX} internal onClick={onClose} />
          </DialogPrimitive.Close>
        )}
      </Section>
      {/* Search input - arrow/enter keys bubble up to Content for centralized handling */}
      <InputTypeIn
        placeholder={placeholder}
        value={value}
        onChange={(e) => onValueChange?.(e.target.value)}
        onKeyDown={handleInputKeyDown}
        autoFocus
      />
    </Section>
  );
}

// =============================================================================
// CommandMenu List
// =============================================================================

/**
 * CommandMenu List Component
 *
 * Scrollable container for menu items with scroll shadows.
 */
function CommandMenuList({ children, emptyMessage }: CommandMenuListProps) {
  const childCount = React.Children.count(children);

  if (childCount === 0 && emptyMessage) {
    return (
      <div className="bg-background-tint-01 flex-1 min-h-0">
        <Section padding={1}>
          <Text secondaryBody text03>
            {emptyMessage}
          </Text>
        </Section>
      </div>
    );
  }

  return (
    <>
      <Separator noPadding />
      <ShadowDiv
        className="flex-1 min-h-0 bg-background-tint-01"
        backgroundColor="var(--background-tint-01)"
        data-command-menu-list
      >
        <Section padding={0.5} gap={0} alignItems="stretch">
          {children}
        </Section>
      </ShadowDiv>
    </>
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
      registerItem(value, () => onSelect());
      return () => unregisterItem(value);
    }
  }, [value, isApplied, onSelect, registerItem, unregisterItem]);

  // When filter is applied, show as group label (non-interactive)
  if (isApplied) {
    return (
      <div className="px-2 py-1.5">
        <Text secondaryBody text03>
          {children}
        </Text>
      </div>
    );
  }

  const isHighlighted = value === highlightedValue;

  // Selectable filter - uses LineItem, delegates all events to context
  return (
    <div data-command-item={value}>
      <LineItem
        icon={icon}
        rightChildren={<SvgChevronRight className="w-4 h-4 stroke-text-02" />}
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

  return (
    <div data-command-item={value}>
      <LineItem
        icon={icon}
        rightChildren={rightContent}
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
    registerItem(value, () => onSelect?.(value));
    return () => unregisterItem(value);
  }, [value, onSelect, registerItem, unregisterItem]);

  const isHighlighted = value === highlightedValue;

  return (
    <div data-command-item={value}>
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
    <>
      <Separator noPadding />
      <Section
        flexDirection="row"
        justifyContent="start"
        gap={1}
        padding={0.75}
      >
        {leftActions}
      </Section>
    </>
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
    <div className="flex items-center gap-1">
      <Icon className="w-[0.875rem] h-[0.875rem] stroke-text-02" />
      <Text figureKeystroke text02>
        {label}
      </Text>
    </div>
  );
}

// =============================================================================
// Export Compound Component
// =============================================================================

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
