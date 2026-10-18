"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { InputTypeIn } from "@opal/components";
import { useSearchField } from "@opal/hooks";

interface PluginDirectoryToolbarProps {
  searchLabel: string;
  query: string;
  onQueryChange: (query: string) => void;
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
  filters,
}: PluginDirectoryToolbarProps) {
  const t = useTranslations("actions.plugins");
  const search = useSearchField({ value: query, onChange: onQueryChange });

  return (
    // Search grows 2:1 against the filter tabs, as on the Agents page.
    <div className="flex flex-row items-center gap-2">
      <div className="min-w-0 flex-2">
        <InputTypeIn
          ref={search.ref}
          searchIcon
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          onKeyDown={search.onKeyDown}
          // The placeholder names the hotkey; the field's name stays short.
          placeholder={t("search.hotkeyPlaceholder")}
          aria-label={searchLabel}
        />
      </div>
      {filters && <div className="min-w-0 flex-1">{filters}</div>}
    </div>
  );
}
