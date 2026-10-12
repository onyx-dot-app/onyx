"use client";

import { useState } from "react";
import { useUser } from "@/providers/UserProvider";
import { useWorkspaceListing, useOutputRefreshStatus } from "@/lib/build/hooks";
import { useTranslations } from "next-intl";
import { Button, Text } from "@opal/components";
import { SvgChevronLeft, SvgChevronRight } from "@opal/icons";
import { SWR_KEYS } from "@/lib/swr-keys";
import { getFileIcon } from "@/lib/utils";
import {
  loadSearchInventory,
  MAX_SEARCH_ENTRIES,
} from "@/app/craft/services/workspaceFiles";
import type { SearchInventory } from "@/lib/build/types";

interface WorkspaceSearchProps {
  sessionId: string;
  query: string;
  refreshKey: number;
  isActive: boolean;
  onFileClick: (path: string, name: string) => void;
  onRefreshingChange?: (refreshing: boolean) => void;
}

export function WorkspaceSearch({
  sessionId,
  query,
  refreshKey,
  isActive,
  onFileClick,
  onRefreshingChange,
}: WorkspaceSearchProps) {
  const { user } = useUser();
  const { data, error, isValidating } = useWorkspaceListing(
    [SWR_KEYS.buildSessionWorkspaceInventory(sessionId), user?.id],
    (signal) => loadSearchInventory(sessionId, signal),
    {
      isActive: isActive && Boolean(user?.id),
      refreshGeneration: refreshKey,
      merge: mergeSearchInventory,
    }
  );
  useOutputRefreshStatus(isActive && isValidating, onRefreshingChange);
  return (
    <SearchResults
      key={query}
      query={query}
      data={data}
      error={error}
      onFileClick={onFileClick}
    />
  );
}

function SearchResults({
  query,
  data,
  error,
  onFileClick,
}: Pick<WorkspaceSearchProps, "query" | "onFileClick"> & {
  data: SearchInventory | undefined;
  error: Error | undefined;
}) {
  const t = useTranslations("craft.filesTab");
  const [page, setPage] = useState(0);
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const matches =
    data?.entries.filter((entry) =>
      entry.path.toLocaleLowerCase().includes(normalizedQuery)
    ) ?? [];
  const maxPage = Math.max(0, Math.ceil(matches.length / 100) - 1);
  const currentPage = Math.min(page, maxPage);
  return (
    <div className="h-full flex flex-col min-h-0">
      <div className="flex-1 overflow-auto p-2">
        {(error || data?.complete === false) && (
          <div role="alert">
            <Text font="secondary-body" color="text-03">
              {t(data ? "partial.label" : "error.title")}
            </Text>
          </div>
        )}
        {!data && !error && (
          <Text font="secondary-body" color="text-03">
            {t("loading.label")}
          </Text>
        )}
        {data?.complete && !matches.length && (
          <Text font="secondary-body" color="text-03">
            {t("noMatches.label")}
          </Text>
        )}
        {matches
          .slice(currentPage * 100, (currentPage + 1) * 100)
          .map((entry) => (
            <div key={entry.path} className="py-0.5">
              <Button
                width="full"
                prominence="tertiary"
                size="sm"
                icon={getFileIcon(entry.name)}
                tooltip={entry.path}
                onClick={() => onFileClick(entry.path, entry.name)}
              >
                {entry.path}
              </Button>
            </div>
          ))}
      </div>
      {maxPage > 0 && (
        <div className="shrink-0 flex items-center justify-center gap-2 p-2">
          <Button
            icon={SvgChevronLeft}
            disabled={currentPage === 0}
            tooltip={t("previousPage.label")}
            onClick={() => setPage(currentPage - 1)}
            prominence="tertiary"
            size="sm"
          />
          <Text font="secondary-body">
            {t("page.label", { page: currentPage + 1, total: maxPage + 1 })}
          </Text>
          <Button
            icon={SvgChevronRight}
            disabled={currentPage === maxPage}
            tooltip={t("nextPage.label")}
            onClick={() => setPage(currentPage + 1)}
            prominence="tertiary"
            size="sm"
          />
        </div>
      )}
    </div>
  );
}

function mergeSearchInventory(
  previous: SearchInventory | undefined,
  inventory: SearchInventory
): SearchInventory {
  if (inventory.complete || !previous) return inventory;
  const entries = new Map(
    previous.entries
      .filter((entry) =>
        inventory.failedDirectories.some(
          (directory) => !directory || entry.path.startsWith(`${directory}/`)
        )
      )
      .map((entry) => [entry.path, entry])
  );
  inventory.entries.forEach((entry) => entries.set(entry.path, entry));
  return {
    ...inventory,
    entries: [...entries.values()].slice(0, MAX_SEARCH_ENTRIES),
  };
}
