import type { IconProps } from "@opal/types";

// =============================================================================
// CommandMenu Entry Types (Discriminated Union)
// =============================================================================

/**
 * Base interface for all CommandMenu items
 * Contains common properties used for filtering and display
 */
interface CommandMenuEntryBase {
  id: string;
  label: string;
  description?: string;
  icon?: React.FunctionComponent<IconProps>;
}

/**
 * Filter entry - clicking adds a filter to narrow results
 * Used for section titles that can filter the list
 */
export interface CommandMenuFilterEntry extends CommandMenuEntryBase {
  type: "filter";
}

/**
 * Clickable item entry - navigates or performs an action
 * Used for sessions, projects, documents with timestamps
 */
export interface CommandMenuClickableEntry extends CommandMenuEntryBase {
  type: "item";
  rightContent?: React.ReactNode; // For timestamps, badges, etc.
}

/**
 * Action entry - performs a quick action with optional keyboard shortcut
 * Used for "New Session", "New Project", etc.
 */
export interface CommandMenuActionEntry extends CommandMenuEntryBase {
  type: "action";
  shortcut?: string; // e.g., "⌘N", "⌘P"
}

/**
 * Discriminated union of all entry types
 * Use `entry.type` to discriminate between types
 */
export type CommandMenuEntry =
  | CommandMenuFilterEntry
  | CommandMenuClickableEntry
  | CommandMenuActionEntry;

// =============================================================================
// CommandMenu Group Types
// =============================================================================

/**
 * Group structure for organizing menu entries
 */
export interface CommandMenuGroup {
  id: string;
  title: string;
  titleSelectable?: boolean; // When true, clicking title adds a filter
  items: CommandMenuEntry[];
}

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
  children: string;
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
  children: string;
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
  isKeyboardNav: boolean;

  // Registration (items call on mount with their callback)
  registerItem: (
    value: string,
    onSelect: () => void,
    type?: "filter" | "item" | "action"
  ) => void;
  unregisterItem: (value: string) => void;

  // Mouse interaction (items call on events - centralized in root)
  onItemMouseEnter: (value: string) => void;
  onItemMouseMove: (value: string) => void;
  onItemClick: (value: string) => void;

  // Keyboard handler (Content attaches this to DialogPrimitive.Content)
  handleKeyDown: (e: React.KeyboardEvent) => void;
}
