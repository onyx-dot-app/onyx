"use client";

import React, {
  createContext,
  useContext,
  useEffect,
  useCallback,
} from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { cn } from "@/lib/utils";
import type { IconProps } from "@opal/types";
import Text from "@/refresh-components/texts/Text";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import LineItem from "@/refresh-components/buttons/LineItem";
import EditableTag from "@/refresh-components/buttons/EditableTag";
import IconButton from "@/refresh-components/buttons/IconButton";
import ShadowDiv from "@/refresh-components/ShadowDiv";
import Separator from "@/refresh-components/Separator";
import { Section } from "@/layouts/general-layouts";
import { SvgChevronRight, SvgSearch, SvgX } from "@opal/icons";
import { useItemRegistry, useCommandMenuKeyboard } from "./hooks";
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
 * CommandMenu Root Component
 *
 * Wrapper around Radix Dialog.Root for managing command menu state.
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
  const [highlightedIndex, setHighlightedIndex] = React.useState(-1);
  const [isKeyboardNav, setIsKeyboardNav] = React.useState(false);
  const {
    registerItem,
    unregisterItem,
    getItemIndex,
    getItemByIndex,
    itemCount,
    resetItems,
  } = useItemRegistry();

  // Reset state when menu closes
  useEffect(() => {
    if (!open) {
      setHighlightedIndex(-1);
      setIsKeyboardNav(false);
      resetItems();
    }
  }, [open, resetItems]);

  const onItemSelect = useCallback(
    (value: string) => {
      onOpenChange(false);
    },
    [onOpenChange]
  );

  const contextValue: CommandMenuContextValue = {
    highlightedIndex,
    setHighlightedIndex,
    isKeyboardNav,
    setIsKeyboardNav,
    registerItem,
    unregisterItem,
    getItemIndex,
    itemCount,
    onItemSelect,
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
 */
const CommandMenuContent = React.forwardRef<
  React.ComponentRef<typeof DialogPrimitive.Content>,
  CommandMenuContentProps
>(({ children }, ref) => {
  const { itemCount, highlightedIndex, setHighlightedIndex, setIsKeyboardNav } =
    useCommandMenuContext();

  // Use the hook instead of inline implementation
  const { handleKeyDown } = useCommandMenuKeyboard({
    isOpen: true, // Always true when Content is rendered
    setIsOpen: () => {}, // No-op since Radix Dialog handles closing
    highlightedIndex,
    setHighlightedIndex,
    setIsKeyboardNav,
    itemCount,
    onSelect: () => {}, // No-op since Enter is handled by individual items
  });

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
 */
function CommandMenuHeader({
  placeholder = "Search...",
  filters = [],
  value = "",
  onValueChange,
  onFilterRemove,
  onClose,
}: CommandMenuHeaderProps) {
  const { setHighlightedIndex, setIsKeyboardNav } = useCommandMenuContext();

  const handleValueChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    onValueChange?.(e.target.value);
    // Reset highlight when search changes
    setHighlightedIndex(-1);
    setIsKeyboardNav(false);
  };

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
      {/* Search input */}
      <InputTypeIn
        placeholder={placeholder}
        value={value}
        onChange={handleValueChange}
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
 * Uses LineItem for consistent styling and keyboard navigation support.
 */
function CommandMenuFilter({
  value,
  children,
  icon,
  isApplied,
  onSelect,
}: CommandMenuFilterProps) {
  const {
    highlightedIndex,
    setHighlightedIndex,
    isKeyboardNav,
    setIsKeyboardNav,
    registerItem,
    unregisterItem,
    getItemIndex,
    onItemSelect,
  } = useCommandMenuContext();

  // Only register for keyboard nav when selectable (not applied)
  useEffect(() => {
    if (!isApplied && onSelect) {
      registerItem(value);
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

  const itemIndex = getItemIndex(value);
  const isHighlighted = itemIndex === highlightedIndex && itemIndex !== -1;

  const handleClick = () => {
    onSelect?.();
  };

  const handleMouseEnter = () => {
    if (!isKeyboardNav && onSelect) {
      setHighlightedIndex(itemIndex);
    }
  };

  const handleMouseMove = () => {
    if (onSelect) {
      if (isKeyboardNav) {
        setIsKeyboardNav(false);
      }
      if (highlightedIndex !== itemIndex) {
        setHighlightedIndex(itemIndex);
      }
    }
  };

  // Handle Enter key on highlighted filter
  useEffect(() => {
    if (isHighlighted && isKeyboardNav && onSelect) {
      const handleKeyDown = (e: KeyboardEvent) => {
        if (e.key === "Enter") {
          e.preventDefault();
          handleClick();
        }
      };
      window.addEventListener("keydown", handleKeyDown);
      return () => window.removeEventListener("keydown", handleKeyDown);
    }
  }, [isHighlighted, isKeyboardNav, onSelect]);

  // Selectable filter - uses LineItem for consistent styling and keyboard nav
  return (
    <LineItem
      icon={icon}
      rightChildren={<SvgChevronRight className="w-4 h-4 stroke-text-02" />}
      emphasized={isHighlighted}
      selected={isHighlighted}
      onClick={handleClick}
      onMouseEnter={handleMouseEnter}
      onMouseMove={handleMouseMove}
    >
      {children}
    </LineItem>
  );
}

// =============================================================================
// CommandMenu Item
// =============================================================================

/**
 * CommandMenu Item Component
 *
 * Wraps LineItem with keyboard navigation support.
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
    highlightedIndex,
    setHighlightedIndex,
    isKeyboardNav,
    setIsKeyboardNav,
    registerItem,
    unregisterItem,
    getItemIndex,
    onItemSelect,
  } = useCommandMenuContext();

  // Register item on mount
  useEffect(() => {
    registerItem(value);
    return () => unregisterItem(value);
  }, [value, registerItem, unregisterItem]);

  const itemIndex = getItemIndex(value);
  const isHighlighted = itemIndex === highlightedIndex && itemIndex !== -1;

  const handleClick = () => {
    onSelect?.(value);
    onItemSelect(value);
  };

  const handleMouseEnter = () => {
    if (!isKeyboardNav) {
      setHighlightedIndex(itemIndex);
    }
  };

  const handleMouseMove = () => {
    // Switch back to mouse mode and update highlight
    if (isKeyboardNav) {
      setIsKeyboardNav(false);
    }
    if (highlightedIndex !== itemIndex) {
      setHighlightedIndex(itemIndex);
    }
  };

  // Handle Enter key on highlighted item
  useEffect(() => {
    if (isHighlighted && isKeyboardNav) {
      const handleKeyDown = (e: KeyboardEvent) => {
        if (e.key === "Enter") {
          e.preventDefault();
          handleClick();
        }
      };
      window.addEventListener("keydown", handleKeyDown);
      return () => window.removeEventListener("keydown", handleKeyDown);
    }
  }, [isHighlighted, isKeyboardNav]);

  return (
    <LineItem
      icon={icon}
      rightChildren={rightContent}
      emphasized={isHighlighted}
      selected={isHighlighted}
      onClick={handleClick}
      onMouseEnter={handleMouseEnter}
      onMouseMove={handleMouseMove}
    >
      {children}
    </LineItem>
  );
}

// =============================================================================
// CommandMenu Action
// =============================================================================

/**
 * CommandMenu Action Component
 *
 * Quick action with optional keyboard shortcut.
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
    highlightedIndex,
    setHighlightedIndex,
    isKeyboardNav,
    setIsKeyboardNav,
    registerItem,
    unregisterItem,
    getItemIndex,
    onItemSelect,
  } = useCommandMenuContext();

  // Register item on mount
  useEffect(() => {
    registerItem(value);
    return () => unregisterItem(value);
  }, [value, registerItem, unregisterItem]);

  const itemIndex = getItemIndex(value);
  const isHighlighted = itemIndex === highlightedIndex && itemIndex !== -1;

  const handleClick = () => {
    onSelect?.(value);
    onItemSelect(value);
  };

  const handleMouseEnter = () => {
    if (!isKeyboardNav) {
      setHighlightedIndex(itemIndex);
    }
  };

  const handleMouseMove = () => {
    // Switch back to mouse mode and update highlight
    if (isKeyboardNav) {
      setIsKeyboardNav(false);
    }
    if (highlightedIndex !== itemIndex) {
      setHighlightedIndex(itemIndex);
    }
  };

  // Handle Enter key on highlighted action
  useEffect(() => {
    if (isHighlighted && isKeyboardNav) {
      const handleKeyDown = (e: KeyboardEvent) => {
        if (e.key === "Enter") {
          e.preventDefault();
          handleClick();
        }
      };
      window.addEventListener("keydown", handleKeyDown);
      return () => window.removeEventListener("keydown", handleKeyDown);
    }
  }, [isHighlighted, isKeyboardNav]);

  return (
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
      onClick={handleClick}
      onMouseEnter={handleMouseEnter}
      onMouseMove={handleMouseMove}
    >
      {children}
    </LineItem>
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
