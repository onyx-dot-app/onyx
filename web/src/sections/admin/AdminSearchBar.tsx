"use client";

import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";

interface AdminSearchBarProps {
  /** Current search query. */
  searchQuery: string;
  /** Called when the search query changes. */
  onSearchQueryChange: (query: string) => void;
  /** Search input placeholder. */
  placeholder?: string;
  /** Action buttons rendered to the right of the search input. */
  children?: React.ReactNode;
}

/**
 * AdminSearchBar — a layout component for simple admin list pages.
 *
 * Renders an internal-variant search input on the left with action buttons
 * (passed as children) on the right. Used on admin pages that have a flat
 * list of items with no advanced filtering — e.g. Service Accounts, Groups,
 * OpenAPI Actions, MCP Servers.
 *
 * The search input stretches to fill available space (`flex-1` via
 * InputTypeIn) while children (typically a primary "New …" button) sit
 * to the right without shrinking.
 *
 * @example
 * ```tsx
 * <AdminSearchBar
 *   searchQuery={search}
 *   onSearchQueryChange={setSearch}
 *   placeholder="Search service accounts..."
 * >
 *   <Button rightIcon={SvgPlusCircle} onClick={handleCreate}>
 *     New Service Account
 *   </Button>
 * </AdminSearchBar>
 * ```
 */
export default function AdminSearchBar({
  searchQuery,
  onSearchQueryChange,
  placeholder = "Search...",
  children,
}: AdminSearchBarProps) {
  return (
    <div className="flex flex-row gap-3 items-center">
      <InputTypeIn
        variant="internal"
        leftSearchIcon
        placeholder={placeholder}
        value={searchQuery}
        onChange={(e) => onSearchQueryChange(e.target.value)}
        showClearButton={false}
      />
      {children}
    </div>
  );
}
