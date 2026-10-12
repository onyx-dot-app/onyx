"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useUser } from "@/providers/UserProvider";
import { isAuthStatusError, isNotFoundError } from "@/lib/fetcher";
import {
  readWorkspaceDirectorySnapshot,
  saveWorkspaceDirectorySnapshot,
  clearWorkspaceDirectorySnapshots,
} from "@/app/craft/services/workspaceDirectorySnapshots";
import { useWorkspaceListing } from "@/lib/build/hooks";
import type { FileSystemEntry } from "@/app/craft/types/streamingTypes";
import { SWR_KEYS } from "@/lib/swr-keys";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import {
  downloadArtifactFile,
  downloadDirectory,
  fetchDirectoryListing,
} from "@/app/craft/services/apiServices";
import { getFileIcon } from "@/lib/utils";
import { Button, LineItemButton, Text } from "@opal/components";
import { Hoverable } from "@opal/core";
import { IconLoader } from "@opal/loaders";
import {
  SvgFolder,
  SvgFolderOpen,
  SvgChevronRight,
  SvgChevronDown,
  SvgAlertCircle,
  SvgDownloadCloud,
} from "@opal/icons";

export type DirectoryStatus = "loading" | "error";

interface DirectoryTreeProps {
  sessionId: string;
  path: string;
  depth: number;
  isActive: boolean;
  isVisible?: boolean;
  refreshGeneration: number;
  onStatusChange: (path: string, status: DirectoryStatus | undefined) => void;
  entry?: FileSystemEntry;
  expandedPaths: Set<string>;
  onToggleFolder: (path: string) => void;
  onFileClick: (path: string, fileName: string) => void;
  onReady?: () => void;
}

export function DirectoryTree({
  sessionId,
  path,
  isActive,
  isVisible = isActive,
  refreshGeneration,
  onStatusChange,
  entry,
  depth,
  expandedPaths,
  onToggleFolder,
  onFileClick,
  onReady,
}: DirectoryTreeProps) {
  const t = useTranslations("craft.filesTab");
  const expanded = !entry || expandedPaths.has(path);
  const listingActive = isActive && expanded;
  const { user } = useUser();
  const userId = user?.id;
  const fallbackData = useMemo(
    () =>
      userId
        ? readWorkspaceDirectorySnapshot(userId, sessionId, path)
        : undefined,
    [userId, sessionId, path]
  );
  const { data, error, isValidating, isCurrentGeneration } =
    useWorkspaceListing(
      [SWR_KEYS.buildSessionFiles(sessionId), userId, path],
      async (signal) => {
        try {
          const listing = await fetchDirectoryListing(sessionId, path, signal);
          signal.throwIfAborted();
          if (userId)
            saveWorkspaceDirectorySnapshot(userId, sessionId, listing);
          return listing;
        } catch (failure) {
          signal.throwIfAborted();
          if (
            userId &&
            (isAuthStatusError(failure) || isNotFoundError(failure))
          )
            clearWorkspaceDirectorySnapshots(userId, sessionId);
          throw failure;
        }
      },
      {
        isActive: listingActive && Boolean(userId),
        isVisible,
        refreshGeneration,
        fallbackData,
      }
    );

  const isLoading =
    listingActive &&
    (isValidating || ((!data || !isCurrentGeneration) && !error));
  const failed = error && error.name !== "AbortError" && !isLoading;
  const status = !listingActive
    ? undefined
    : isLoading
      ? "loading"
      : failed
        ? "error"
        : undefined;
  useEffect(() => {
    onStatusChange(path, status);
  }, [path, status, onStatusChange]);
  useEffect(
    () => () => onStatusChange(path, undefined),
    [path, onStatusChange]
  );

  useEffect(() => {
    if (!listingActive || !isCurrentGeneration || !data || isLoading || error)
      return;
    const store = useBuildSessionStore.getState();
    const saved =
      store.sessions.get(sessionId)?.filesTabState.expandedPaths ?? [];
    const folders = new Set(
      data.entries
        .filter((child) => child.is_directory)
        .map((child) => child.path)
    );
    const missing = saved.filter((expandedPath) => {
      const parent = expandedPath.includes("/")
        ? expandedPath.slice(0, expandedPath.lastIndexOf("/"))
        : "";
      return parent === path && !folders.has(expandedPath);
    });
    if (missing.length)
      store.updateFilesTabState(sessionId, {
        expandedPaths: saved.filter(
          (expandedPath) =>
            !missing.some(
              (removed) =>
                expandedPath === removed ||
                expandedPath.startsWith(`${removed}/`)
            )
        ),
      });
  }, [
    data,
    isLoading,
    error,
    listingActive,
    isCurrentGeneration,
    sessionId,
    path,
    expandedPaths,
    onToggleFolder,
  ]);

  const hasData = data !== undefined;
  useEffect(() => {
    if (hasData) onReady?.();
  }, [hasData, onReady]);

  const rowDepth = entry ? depth + 1 : depth;
  const content = !data ? (
    path ? null : (
      <div className="px-3 py-2" role={failed ? "alert" : "status"}>
        <Text font="secondary-body" color="text-03">
          {failed ? t("error.title") : t("loading.label")}
        </Text>
      </div>
    )
  ) : data.entries.length === 0 ? (
    <div
      className="py-1.5 pe-3"
      style={{ paddingInlineStart: rowDepth * 16 + 8 }}
      role={failed ? "alert" : undefined}
    >
      <Text font="secondary-body" color="text-03">
        {failed
          ? t("error.title")
          : path
            ? t("emptyDirectory.label")
            : t("empty.title")}
      </Text>
    </div>
  ) : (
    <>
      {failed && (
        <div role="alert">
          <Text font="secondary-body" color="text-03">
            {t("error.title")}
          </Text>
        </div>
      )}
      {[...data.entries]
        .sort((a, b) =>
          a.is_directory !== b.is_directory
            ? a.is_directory
              ? -1
              : 1
            : a.name.localeCompare(b.name)
        )
        .map((child) =>
          child.is_directory ? (
            <DirectoryTree
              key={child.path}
              sessionId={sessionId}
              entry={child}
              path={child.path}
              depth={rowDepth}
              isActive={isActive}
              isVisible={isVisible}
              refreshGeneration={refreshGeneration}
              onStatusChange={onStatusChange}
              expandedPaths={expandedPaths}
              onToggleFolder={onToggleFolder}
              onFileClick={onFileClick}
            />
          ) : (
            <WorkspaceEntryRow
              key={child.path}
              sessionId={sessionId}
              entry={child}
              depth={rowDepth}
              onClick={() => onFileClick(child.path, child.name)}
            />
          )
        )}
    </>
  );
  return (
    <>
      {entry && (
        <WorkspaceEntryRow
          sessionId={sessionId}
          entry={entry}
          depth={depth}
          expanded={expanded}
          status={status}
          onClick={() => onToggleFolder(entry.path)}
        />
      )}
      {expanded && content}
    </>
  );
}

function WorkspaceEntryRow({
  sessionId,
  entry,
  depth,
  expanded,
  status,
  onClick,
}: {
  sessionId: string;
  entry: FileSystemEntry;
  depth: number;
  expanded?: boolean;
  status?: DirectoryStatus;
  onClick: () => void;
}) {
  const t = useTranslations("craft.filesTab");
  const loadingStartedAt = useRef(0);
  const [holdLoadingIcon, setHoldLoadingIcon] = useState(false);
  useEffect(() => {
    if (status === "loading") {
      loadingStartedAt.current = Date.now();
      setHoldLoadingIcon(true);
      return;
    }
    const remaining = 150 - (Date.now() - loadingStartedAt.current);
    if (remaining <= 0 || !expanded || status === "error") {
      setHoldLoadingIcon(false);
      return;
    }
    const timer = setTimeout(() => setHoldLoadingIcon(false), remaining);
    return () => clearTimeout(timer);
  }, [status, expanded]);
  // The visual minimum never delays rows or keeps the reload control busy.
  const showLoadingIcon =
    expanded &&
    (status === "loading" || (holdLoadingIcon && status !== "error"));
  const Icon = entry.is_directory
    ? showLoadingIcon
      ? IconLoader
      : status === "error"
        ? SvgAlertCircle
        : expanded
          ? SvgFolderOpen
          : SvgFolder
    : getFileIcon(entry.name);
  return (
    <div className="relative" style={{ paddingInlineStart: depth * 16 }}>
      <Hoverable.Root group="workspace-file-row">
        <LineItemButton
          width="full"
          title={entry.name}
          titleMaxLines={1}
          sizePreset="secondary"
          variant="body"
          padding={0}
          rounding={1}
          aria-expanded={entry.is_directory ? expanded : undefined}
          aria-busy={status === "loading" || undefined}
          aria-label={entry.name}
          icon={Icon}
          rightChildren={
            <div className="flex items-center gap-1">
              <Hoverable.Item
                group="workspace-file-row"
                variant="appear-on-hover"
              >
                <Button
                  icon={SvgDownloadCloud}
                  prominence="tertiary"
                  size="xs"
                  tooltip={t("download.label")}
                  aria-label={t("download.label")}
                  onClick={(event) => {
                    event.stopPropagation();
                    if (entry.is_directory)
                      downloadDirectory(sessionId, entry.path);
                    else downloadArtifactFile(sessionId, entry.path);
                  }}
                />
              </Hoverable.Item>
              {entry.is_directory &&
                (expanded ? (
                  <SvgChevronDown size={12} />
                ) : (
                  <SvgChevronRight size={12} />
                ))}
            </div>
          }
          onClick={onClick}
        />
      </Hoverable.Root>
    </div>
  );
}
