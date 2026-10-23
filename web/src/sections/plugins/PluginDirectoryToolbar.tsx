import type { ReactNode } from "react";
import { InputTypeIn } from "@opal/components";

interface PluginDirectoryToolbarProps {
  searchLabel: string;
  query: string;
  onQueryChange: (query: string) => void;
  filters?: ReactNode;
}

export default function PluginDirectoryToolbar({
  searchLabel,
  query,
  onQueryChange,
  filters,
}: PluginDirectoryToolbarProps) {
  return (
    <div className="flex flex-col-reverse gap-4 md:flex-row md:items-center md:justify-between">
      <div className="min-w-0 flex-1">{filters}</div>
      <div className="flex min-w-0 flex-wrap items-center justify-end gap-2">
        <div className="min-w-0 flex-1 md:w-64 md:flex-none">
          <InputTypeIn
            searchIcon
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder={searchLabel}
            aria-label={searchLabel}
          />
        </div>
      </div>
    </div>
  );
}
