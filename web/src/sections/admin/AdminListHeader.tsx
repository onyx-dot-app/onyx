"use client";

import { Button, Card } from "@opal/components";
import { Content } from "@opal/layouts";
import { SvgPlusCircle } from "@opal/icons";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";

interface AdminListHeaderProps {
  /** Whether items exist — controls search bar vs empty-state card. */
  hasItems: boolean;
  /** Current search query. */
  searchQuery: string;
  /** Called when the search query changes. */
  onSearchQueryChange: (query: string) => void;
  /** Search input placeholder. */
  placeholder?: string;
  /** Text shown in the empty-state card when no items exist. */
  emptyStateText: string;
  /** Called when the action button is clicked. */
  onAction: () => void;
  /** Label for the action button. */
  actionLabel: string;
}

/**
 * AdminListHeader — the top bar for simple admin list pages.
 *
 * Handles two states:
 *
 * 1. **Items exist** (`hasItems = true`): renders a search input on the left
 *    with a primary action button on the right.
 * 2. **No items** (`hasItems = false`): renders a bordered card with
 *    descriptive text on the left and the same action button on the right.
 *
 * The action button always renders with a `SvgPlusCircle` right icon.
 *
 * Used on admin pages that have a flat list of items with no advanced
 * filtering — e.g. Service Accounts, Groups, OpenAPI Actions, MCP Servers.
 *
 * @example
 * ```tsx
 * <AdminListHeader
 *   hasItems={items.length > 0}
 *   searchQuery={search}
 *   onSearchQueryChange={setSearch}
 *   placeholder="Search service accounts..."
 *   emptyStateText="Create service account API keys with user-level access."
 *   onAction={handleCreate}
 *   actionLabel="New Service Account"
 * />
 * ```
 */
export default function AdminListHeader({
  hasItems,
  searchQuery,
  onSearchQueryChange,
  placeholder = "Search...",
  emptyStateText,
  onAction,
  actionLabel,
}: AdminListHeaderProps) {
  const actionButton = (
    <Button rightIcon={SvgPlusCircle} onClick={onAction}>
      {actionLabel}
    </Button>
  );

  if (!hasItems) {
    return (
      <Card rounding="lg" border="solid">
        <div className="flex flex-row items-center justify-between gap-3">
          <Content
            title={emptyStateText}
            sizePreset="main-ui"
            variant="body"
            prominence="muted"
            widthVariant="fit"
          />
          {actionButton}
        </div>
      </Card>
    );
  }

  return (
    <div className="flex flex-row gap-3 items-center px-2 pb-3">
      <InputTypeIn
        variant="internal"
        leftSearchIcon
        placeholder={placeholder}
        value={searchQuery}
        onChange={(e) => onSearchQueryChange(e.target.value)}
        showClearButton={false}
      />
      {actionButton}
    </div>
  );
}
