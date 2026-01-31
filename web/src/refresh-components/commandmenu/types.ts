import type { IconProps } from "@opal/types";

// =============================================================================
// Filter Object (for header display)
// =============================================================================

/**
 * Filter object for CommandMenu header
 */
export interface CommandMenuFilter {
  id: string;
  label: string;
  icon?: React.FunctionComponent<IconProps>;
}

/**
 * Props for CommandMenu root component
 */
export interface CommandMenuProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: React.ReactNode;
}

/**
 * Props for CommandMenu content (modal container)
 */
export interface CommandMenuContentProps {
  children: React.ReactNode;
}

/**
 * Props for CommandMenu header with search and filters
 */
export interface CommandMenuHeaderProps {
  placeholder?: string;
  filters?: CommandMenuFilter[];
  value?: string;
  onValueChange?: (value: string) => void;
  onFilterRemove?: (filterId: string) => void;
  onClose?: () => void;
  onEmptyBackspace?: () => void;
}

/**
 * Props for CommandMenu list container
 */
export interface CommandMenuListProps {
  children: React.ReactNode;
  emptyMessage?: string;
}

/**
 * Props for CommandMenu filter (selectable or as applied group label)
 */
export interface CommandMenuFilterProps {
  /**
   * Unique identifier for this item within the CommandMenu.
   * Must be unique across all Filter, Item, and Action components.
   * Used for keyboard navigation, selection callbacks, and highlight state.
   */
  value: string;
  children: string;
  icon?: React.FunctionComponent<IconProps>;
  isApplied?: boolean; // When true, renders as non-interactive group label
  onSelect?: () => void;
}

/**
 * Props for CommandMenu item
 */
export interface CommandMenuItemProps {
  /**
   * Unique identifier for this item within the CommandMenu.
   * Must be unique across all Filter, Item, and Action components.
   * Used for keyboard navigation, selection callbacks, and highlight state.
   */
  value: string;
  icon?: React.FunctionComponent<IconProps>;
  rightContent?:
    | React.ReactNode
    | ((params: { isHighlighted: boolean }) => React.ReactNode); // For timestamps, badges, etc.
  onSelect?: (value: string) => void;
  children: React.ReactNode;
}

/**
 * Props for CommandMenu action (quick actions with keyboard shortcuts)
 */
export interface CommandMenuActionProps {
  /**
   * Unique identifier for this item within the CommandMenu.
   * Must be unique across all Filter, Item, and Action components.
   * Used for keyboard navigation, selection callbacks, and highlight state.
   */
  value: string;
  icon?: React.FunctionComponent<IconProps>;
  shortcut?: string; // Keyboard shortcut like "⌘N", "⌘P"
  onSelect?: (value: string) => void;
  children: React.ReactNode;
  /**
   * Whether this action should be considered for initial highlight.
   * Default: true. Set false to skip this item when determining initial highlight.
   * Arrow key navigation still includes all items regardless of this setting.
   */
  defaultHighlight?: boolean;
}

/**
 * Props for CommandMenu footer
 */
export interface CommandMenuFooterProps {
  leftActions?: React.ReactNode;
}

/**
 * Props for CommandMenu footer action hint
 */
export interface CommandMenuFooterActionProps {
  icon: React.FunctionComponent<IconProps>;
  label: string;
}

/**
 * Context value for CommandMenu keyboard navigation
 * Uses centralized control with callback registry - items are "dumb" renderers
 */
export interface CommandMenuContextValue {
  // State
  highlightedValue: string | null;
  highlightedItemType: "filter" | "item" | "action" | null;
  isKeyboardNav: boolean;

  // Registration (items call on mount with their callback)
  registerItem: (
    value: string,
    onSelect: () => void,
    type?: "filter" | "item" | "action",
    defaultHighlight?: boolean
  ) => void;
  unregisterItem: (value: string) => void;

  // Mouse interaction (items call on events - centralized in root)
  onItemMouseEnter: (value: string) => void;
  onItemMouseMove: (value: string) => void;
  onItemClick: (value: string) => void;
  onListMouseLeave: () => void;

  // Keyboard handler (Content attaches this to DialogPrimitive.Content)
  handleKeyDown: (e: React.KeyboardEvent) => void;
}
