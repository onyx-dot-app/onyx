"use client";

import { Button } from "@opal/components";
import { Card } from "@opal/components";
import { Content } from "@opal/layouts";
import { SvgPlusCircle } from "@opal/icons";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";

interface SimpleAdminSearchProps {
  /** Whether items exist (controls search vs empty state). */
  hasItems: boolean;
  /** Current search query. */
  searchQuery: string;
  /** Called when the search query changes. */
  onSearchQueryChange: (query: string) => void;
  /** Search input placeholder. */
  placeholder?: string;
  /** Called when the action button is clicked. */
  onAction: () => void;
  /** Label for the action button. */
  actionLabel: string;
  /** Text shown in the empty-state card. */
  emptyStateText: string;
}

export default function SimpleAdminSearch({
  hasItems,
  searchQuery,
  onSearchQueryChange,
  placeholder = "Search...",
  onAction,
  actionLabel,
  emptyStateText,
}: SimpleAdminSearchProps) {
  if (!hasItems) {
    return (
      <Card paddingVariant="md" roundingVariant="lg" borderVariant="solid">
        <div className="flex flex-row items-center justify-between gap-3">
          <Content
            title={emptyStateText}
            sizePreset="main-ui"
            variant="body"
            prominence="muted"
            widthVariant="fit"
          />
          <Button rightIcon={SvgPlusCircle} onClick={onAction}>
            {actionLabel}
          </Button>
        </div>
      </Card>
    );
  }

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
      <Button rightIcon={SvgPlusCircle} onClick={onAction}>
        {actionLabel}
      </Button>
    </div>
  );
}
