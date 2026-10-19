"use client";

import type { KeyboardEvent, ReactNode, Ref } from "react";
import { useTranslations } from "next-intl";
import { SearchField, type SearchFieldHandle } from "@/lib/common/components";

interface PluginDirectoryToolbarProps {
  searchLabel: string;
  query: string;
  onQueryChange: (query: string) => void;
  /** The search field's handle and key handler, e.g. from `useSearchResultsNavigation`. */
  searchRef?: Ref<SearchFieldHandle>;
  onSearchKeyDown?: (event: KeyboardEvent<HTMLInputElement>) => void;
  filters?: ReactNode;
}

/**
 * The directory's search and filter row. Search works like the connector
 * catalog's: it is focused on arrival, Escape clears it and then leaves it,
 * and "/" comes back to it.
 */
export default function PluginDirectoryToolbar({
  searchLabel,
  query,
  onQueryChange,
  searchRef,
  onSearchKeyDown,
  filters,
}: PluginDirectoryToolbarProps) {
  const t = useTranslations("actions.plugins");

  return (
    // The filter tabs keep their natural width; search takes the rest.
    <div className="flex flex-row items-center gap-2">
      <div className="min-w-0 flex-1">
        <SearchField
          ref={searchRef}
          value={query}
          onChange={onQueryChange}
          onKeyDown={onSearchKeyDown}
          // The placeholder names the hotkey; the field's name stays short.
          placeholder={t("search.hotkeyPlaceholder")}
          aria-label={searchLabel}
        />
      </div>
      {filters && <div className="shrink-0">{filters}</div>}
    </div>
  );
}
